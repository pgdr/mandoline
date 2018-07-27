#!/usr/bin/env python3

from graph import Graph, DAGError, load_graph
from datastructures import Bimap
from pattern import PatternBuilder, Pattern

import argparse
import itertools
import sys

from collections import defaultdict
from sortedcontainers import SortedSet
from itertools import permutations, product, combinations, chain
import bisect
import math, random
import cairo

from tree_decompose import TD, short_str

import logging

log = logging.getLogger("mandoline")

class Recorder:
    def __init__(self):
        self.pieces = defaultdict(set)
        self.decomps = defaultdict(set)

    def count_linear(self, td, adh_size):
        assert(td.is_linear())
        if td not in self.pieces:
            log.info("Found new piece %s", td.td_string())
        self.pieces[td].add(adh_size)

    def count_recursive(self, td, adh_size):
        assert(not td.is_linear())
        if td in self.decomps and adh_size in self.decomps[td]:
            return True

        self.decomps[td].add(adh_size)
        log.info("Found new decomp/adh size combination %s, %s", td.td_string(), adh_size)
        return False

    def report(self):
        log.info("Recorded %d linear pieces and %d decompositions.", len(self.pieces), len(self.decomps))

def powerset(iterable):
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(0, len(s)+1))

def powerset_nonempty(iterable):
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(1, len(s)+1))

def simulate_count(R, H, td):
    _simulate_count_rec(R, 0, H, td, 0)

def _simulate_count_rec(R, adh_size, H, td, depth):
    prefix = " "*(4*depth)
    log.debug("%sWe want to count %s (%s) for adhesion size %s", prefix, td.td_string(), str(td), adh_size)

    split_depth = td.adhesion_size()
    splits = list(td.split())
    if len(splits) == 1:
        log.debug("%sThis decomposition is linear, we simply count it!", prefix)
        R.count_linear(td, adh_size)
        return

    already_known = R.count_recursive(td, adh_size)
    if already_known:
        return

    log.debug("%sThe decomposition branches at depth %d", prefix, split_depth)

    order_prefix = td._sep[:split_depth]
    td_current = splits[0]
    log.debug("%sWe first count the leftmost piece %s", prefix, td_current)
    _simulate_count_rec(R, split_depth, H, td_current, depth+1)

    log.debug("%sNow we fold-count with the remaining pieces.", prefix)

    for td_next in splits[1:]:
        log.debug("%sThe next piece is %s and we first count it.", prefix, td_next)
        _simulate_count_rec(R, split_depth, H, td_next, depth+1)
        td_previous = td_current
        td_current = td_current.merge(td_next, split_depth)
        log.debug("%sThe initial count of %s is the count of %s times the count of %s", prefix, td_current, td_previous, td_next)   

        for (HH, tdHH) in enumerate_defects(H, td,  td_previous, td_next, td_current, depth):
            _simulate_count_rec(R, split_depth, HH, tdHH, depth+1)

def td_overlap(decompA, decompB):
    """
        Computes three sets of nodes: nodes exclusive to decompA,
        nodes exclusive to decompB and all nodes of the joint
        decomposition (including their joint root-path).
    """
    root_path = set(decompA._sep) & set(decompB._sep)
    nodesA = decompA.nodes()
    nodesB = decompB.nodes()
    common_nodes = nodesA & nodesB
    nodesA -= common_nodes
    nodesB -= common_nodes
    nodesAll = nodesA | nodesB | root_path
    return (nodesA, nodesB, nodesAll)

def enumerate_overlaps(decompA, decompB):
    """
        Enumerates all graphs and td decompositions that 
        contain decompA, decompB as subgraph/subdecompositions
        while overlapping in some subset of vertices.
    """
    root_path = set(decompA._sep) & set(decompB._sep)
    assert len(root_path) > 0 # Paranoia: decompositions must have common root-path.
    nodesA, nodesB, nodesAll = td_overlap(decompA, decompB)

    decompJoint = decompA.merge(decompB, len(root_path))
    # print("{} + {} = {}".format(decompA, decompB, decompJoint))
    dagJoint = decompJoint.to_ditree()
    graphJoint = decompJoint.to_graph()
    # print("TD Tree",dagJoint)
    # print("Graph", graphJoint)

    # Make a list of which nodes in nodesA can potentially be
    # mapped onto nodes in nodesB. The first constraint enforced here
    # is that the must have the same in-neighbourhood w.r.t the 
    # (joint) root-path of the decomposition.
    candidates = {}
    for u in nodesA:
        candidates[u] = set()
        rp_neighboursA = decompA.in_neighbours(u) & root_path
        for v in nodesB:
            rp_neighboursB = decompB.in_neighbours(v) & root_path
            if rp_neighboursA == rp_neighboursB:
                candidates[u].add(v)

    # print(candidates)

    # Now try all subsets of nodesA, including the empty set
    for sourceA in powerset(nodesA):
        candidate_sets = [candidates[x] for x in sourceA]
        subgraphA = graphJoint.subgraph(sourceA)
        for targetB in product(*candidate_sets):
            if len(set(targetB)) != len(targetB):
                continue # Mapping must be onto

            mapping = Bimap()
            mapping.put_all(zip(sourceA, targetB))
            # print("  Mapping {} -> {} = {}".format(sourceA, targetB, mapping))

            # Check that subgraphs induced by 'sourceA' and 'sourceB' are the same
            # under the mapping, e.g. that the mapping is a isomorphism.
            subgraphB = graphJoint.subgraph(targetB)

            if subgraphA.relabel(mapping) != subgraphB:
                continue # Not a isomorphism

            # print("  Isomorphism! {} == {}".format(subgraphA.relabel(mapping), subgraphB))
            
            dagMerged = dagJoint.copy()
            dagMerged.merge_pairs(mapping.items())
            # print("  Dag contraction {} --{}--> {}".format(dagJoint, mapping, dagMerged))

            # Check whether resulting decomposition graph is a DAG, otherwise
            # this mapping is incompatible with the orderings associated with decompA, decompB.
            if not dagMerged.is_acyclic():
                # print("  > not a DAG")
                continue

            # This is going somewhere, so we can finally construct the 
            # resulting graph
            graphMerged = graphJoint.copy()
            graphMerged.merge_pairs(mapping.items())

            # print("  Graph contraction {} --{}--> {}".format(graphJoint, mapping, graphMerged))

            # Decompose resulting graph according to DAG embeddings
            print("  TD decompositions of {}:".format(graphMerged))
            seen_tdM = set()
            for o in dagMerged.embeddings():
                tdM = TD.decompose(graphMerged, o)
                if tdM in seen_tdM:
                    continue
                seen_tdM.add(tdM)

                # print("    {}  /  {}".format(tdM, tdM.td_string()))
                yield graphMerged, tdM, mapping

def enumerate_defects(H, tdH, decompA, decompB, decompMerged, depth):
    """
        Enumerates all possible graphs with td decompositions that contain
        induced subgraph that decompose into decompA, decompB (with the joint
        separator 'separator').
    """
    prefix = " "*(4*depth)

    nodesA, nodesB, nodesAll = td_overlap(decompA, decompB)

    # TODO: enumerate _overlaps_

    graphMerged = H.subgraph(nodesAll)
   
    if graphMerged != decompMerged.to_graph():
        print(graphMerged.hash, decompMerged.to_graph().hash)

    assert graphMerged == decompMerged.to_graph(), "{} != {}".format(graphMerged, decompMerged.to_graph())

    for (HH, tdHH) in enumerate_edge_faults(graphMerged, decompMerged, nodesA, nodesB, depth):
        yield HH, tdHH

def enumerate_edge_faults(H, tdH, nodesA, nodesB, depth):
    """
        
    """
    prefix = " "*(4*depth)
    log.debug("%sTo account for non-induced instance, edges between %s and %s need to be considered", prefix, nodesA, nodesB ) 
    potential_edges = list(product(nodesA, nodesB))

    log.debug("%sWe subtract the results of the following counts:", prefix)
    seen_decomp = set()
    for o in tdH.suborders(H):
        for edges in powerset_nonempty(potential_edges):
            assert len(o) > 0
            HH = H.copy()
            HH.add_edges(edges)
            log.debug("%sDecompositing %s along order %s", prefix,list(HH.edges()), o)                    
            tdHH = TD.decompose(HH, o)
            if tdHH in seen_decomp:
                continue
            seen_decomp.add(tdHH)
            yield (HH, tdHH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Counts H in G')

    parser.add_argument('H', help='Pattern graph H')
    # parser.add_argument('G', help='Host graph G')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--no-reduction', action='store_true' )
    parser.add_argument('--quiet', action='store_true' )

    args = parser.parse_args()

    # Set up logging
    ch = logging.StreamHandler(sys.stdout)
    if args.quiet:
        # Mute on top level, don't add handler
        log.setLevel(logging.CRITICAL)
    elif args.debug:
        ch.setLevel(logging.DEBUG)
        log.setLevel(logging.DEBUG)
        log.addHandler(ch)
    else:
        ch.setLevel(logging.INFO)
        log.setLevel(logging.INFO)
        log.addHandler(ch)

    # Load pattern and graph
    H = load_graph(args.H)
    log.info("Loaded pattern graph with {} vertices and {} edges".format(len(H), H.num_edges()))
    log.info(H)

    # G = load_graph(args.G)
    # log.info("Loaded host graph with {} vertices and {} edges".format(len(G), G.num_edges()))

    # if args.no_reduction:
    #     log.info("Skipping recution procedure because flag --no-reduction was set")
    # else:
    #     mindeg = min(H.degree_sequence()) 
    #     log.info("Computing {}-core of host graph".format(mindeg))
    #     G = G.compute_core(mindeg)
    #     log.info("Reduced host graph to {} vertices and {} edges".format(len(G), G.num_edges()))

    # log.info("Computing {}-wcol sets".format(len(H)-1))
    # LG, mapping = G.to_lgraph()
    # LG.compute_wr(len(H)-1)
    # log.info("Done.")

    seen = set()
    R = Recorder()
    for order in permutations(H):
        tdH = TD.decompose(H, order)
        if tdH in seen:
            continue

        log.info("The decomposition %s represents the following orders:", tdH.order_string())
        for o in tdH.orders():
            log.info("  " + short_str(o))

        seen.add(tdH)
        log.info("")

        simulate_count(R, H, tdH)
        log.info("")

    log.info("\n")
    log.info("Computed %d tree decompositions", len(seen))

    R.report()