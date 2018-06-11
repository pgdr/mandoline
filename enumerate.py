#!/usr/bin/env python3

from graph import Graph, load_graph
from pattern import PatternBuilder, Pattern

import itertools
import sys

from collections import defaultdict
from sortedcontainers import SortedSet
import bisect
import math, random
import cairo

def find_matches(LG, piece, adhesion):
    matches = defaultdict(SortedSet)
    for iu, wreach in LG.wreach_iter():
        for match in LG.match(iu, piece):
            mapped_adhesion = match.restrict_to(adhesion)
            matches[mapped_adhesion].add(iu)
    return matches

G = load_graph('example-graphs/karate.txt.gz')
print("Loaded graph with {} vertices".format(len(G)))

H = Graph()
H.add_edge(0,1)
H.add_edge(1,2)
H.add_edge(2,3)
H.add_edge(3,4)

print(H)

LG, mapping = G.to_lgraph()
LG.compute_wr(len(H)-1)

for P,indexmap in H.enum_patterns():
    truth = []
    if len(G) < 100:
        truth = list(LG.brute_force_enumerate(P))
        print("Found pattern {} times as ordered subgraph by brute force, e.g.".format(len(truth)))
        print(truth[:5], "\n")
    else:
        print("Graph to large to brute force")
    truth = set(truth)

    print("Decomposing pattern:")
    pieces = list(P.decompose())
    adhesions = []

    for i,piece in enumerate(pieces):
        print(i, piece)
        print("  Leaves:", piece.leaves)

        adh = list(sorted(set(piece.leaves) & set(pieces[-1].leaves)))
        adhesions.append(adh)

        print("  Adhesion:", adh)


    print("\nCounting secondary pieces:")
    secondary_matches = []
    for adh,piece in zip(adhesions[:-1], pieces[:-1]):
        matches = find_matches(LG, piece, adh)
        secondary_matches.append(matches)
        print(piece)
        print(matches)

    print("\nAssembling with primary piece:")

    count = 0
    errors = 0
    matches = set()
    for iu, wreach in LG.wreach_iter():
        print("\n")
        print(iu,":")

        uIN = set(LG.in_neighbours(iu))

        # Match primary piece
        for iumatch in LG.match(iu, pieces[-1]):
            print("Attempting to extend", iumatch)

            candidate_roots = []
            candidate_roots_indexed = []
            max_count = 1
            for i,(adh,piece) in enumerate(zip(adhesions[:-1], pieces[:-1])):
                mapped_adh = iumatch.restrict_to(adh)
                cands = secondary_matches[i][mapped_adh]
                
                # We can restrict ourselves to candidates that lie to
                # the left of iu 
                cands = cands[:cands.bisect_right(iu-1)] 

                print("  piece {}: ".format(i), piece)
                print("  adhesion:", mapped_adh)
                print("  candidate roots:", cands)

                candidate_roots.append(cands)
                candidate_roots_indexed.append(list(enumerate(cands)))
                max_count *= len(cands)

            assert len(candidate_roots) > 0 # Hand single-piece pattern case

            if max_count == 0: 
                # At least one candidate set was empty
                continue

            stack = [(0, 0, 0, iumatch)]
            while len(stack):
                print("  STCK",stack)
                start_index, root_lower_bnd, piece_index, match = stack.pop()

                print("  possible candidates:", candidate_roots[piece_index]) 
                print("  restricted candidates:", candidate_roots[piece_index][start_index:])

                lower_index = bisect.bisect_left(candidate_roots[piece_index], root_lower_bnd)
                lower_index = max(lower_index, start_index)

                for i,iv in candidate_roots_indexed[piece_index][lower_index:]:
                    if iv in uIN:
                        continue # Abort: iu, iv are neighbours

                    if piece_index == len(pieces)-2:
                        # Last piece to be matched.  Every match here is
                        # a match for the whole pattern
                        for ivmatch in LG.match(iv, pieces[piece_index], partial_match=match):
                            count += 1
                            matches.add(ivmatch)
                            if ivmatch in truth:
                                print(ivmatch)
                            else:
                                errors += 1
                                print(">>>", ivmatch, "<<<")                    
                    else: 
                        found = False
                        for ivmatch in LG.match(iv, pieces[piece_index], partial_match=match):
                            stack.append((i+1,root_lower_bnd,piece_index,match))
                            stack.append((i+1,iv,piece_index+1,ivmatch))
                            found = True
                            break

                        if found:
                            break
            print("Done with extending", iumatch, "\n")

    print("\n\n")
    print("Total count:", count)
    print("False positives:", errors)

    missing = list(truth - matches)
    print("Not found:", len(missing))
    print("Examples:")
    print(missing[:min(len(missing), 20)])
