# Testbench report

Simulated 40.0 min game time (steady-state window 30.0 min), wall time 23.4 s, Factorio 2.1.23.
Built 241/241 entities, 1 electric network(s).

## Legendary output per hour
- copper-cable: 1,200
- copper-plate: 362
- electronic-circuit: 162
- iron-plate: 86

## Machine utilisation
| machine | recipe | working | main stalls |
|---|---|---|---|
| electromagnetic-plant | copper-cable@epic | 2% | output blocked 50%, missing item input 48% |
| electromagnetic-plant | copper-cable@normal | 91% | output blocked 8%, missing item input 1% |
| electromagnetic-plant | copper-cable@rare | 23% | output blocked 44%, missing item input 34% |
| electromagnetic-plant | copper-cable@uncommon | 40% | missing item input 40%, output blocked 20% |
| electromagnetic-plant | electronic-circuit@epic | 3% | missing item input 97% |
| electromagnetic-plant | electronic-circuit@normal | 100% |  |
| electromagnetic-plant | electronic-circuit@rare | 16% | missing item input 84% |
| electromagnetic-plant | electronic-circuit@uncommon | 36% | missing item input 64% |
| recycler | - | 18% | no input 82% |

## Growing stock (containers)
| item | start | end | per hour |
|---|---|---|---|
| copper-plate@legendary | 43 | 225 | +364 |
| iron-plate@legendary | 21 | 64 | +86 |
| copper-plate@epic | 31 | 36 | +10 |
| copper-plate@rare | 29 | 34 | +10 |
| iron-plate@uncommon | 4 | 5 | +2 |

## Machines stalled more than half the time
- recycler at (-21, 15) : working 0%, mostly no input
- recycler at (-19, -11) : working 7%, mostly no input
- recycler at (-19, 3) : working 2%, mostly no input
- recycler at (-15, 0) : working 7%, mostly no input
- recycler at (-11, 15) : working 0%, mostly no input
- recycler at (-9, -11) : working 12%, mostly no input
- recycler at (-9, 3) : working 0%, mostly no input
- recycler at (-6, 15) : working 12%, mostly no input
- recycler at (-5, -14) : working 0%, mostly no input
- recycler at (-5, 0) : working 0%, mostly no input
- recycler at (-1, 1) : working 2%, mostly no input
- recycler at (-1, 15) : working 12%, mostly no input
- recycler at (1, -11) : working 0%, mostly no input
- recycler at (4, 15) : working 12%, mostly no input
- recycler at (5, -14) : working 12%, mostly no input
- recycler at (9, 1) : working 0%, mostly no input
- recycler at (9, 15) : working 5%, mostly no input
- recycler at (11, -11) : working 5%, mostly no input
- recycler at (14, 1) : working 0%, mostly no input
- recycler at (14, 15) : working 2%, mostly no input
- recycler at (15, -14) : working 24%, mostly no input
- recycler at (19, 1) : working 12%, mostly no input
- electromagnetic-plant at (-20, -4) copper-cable@rare: working 12%, mostly output blocked
- electromagnetic-plant at (-10, -4) copper-cable@epic: working 0%, mostly output blocked
- electromagnetic-plant at (0, 10) copper-cable@uncommon: working 37%, mostly missing item input
- electromagnetic-plant at (5, 10) copper-cable@uncommon: working 39%, mostly missing item input
- electromagnetic-plant at (10, -18) copper-cable@uncommon: working 29%, mostly output blocked
- electromagnetic-plant at (10, 10) copper-cable@rare: working 37%, mostly missing item input
- electromagnetic-plant at (15, 10) copper-cable@epic: working 2%, mostly missing item input
- electromagnetic-plant at (-15, -4) electronic-circuit@rare: working 15%, mostly missing item input
- electromagnetic-plant at (-5, -4) electronic-circuit@epic: working 2%, mostly missing item input
- electromagnetic-plant at (15, -18) electronic-circuit@uncommon: working 34%, mostly missing item input
