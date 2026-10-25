# Testbench report

Simulated 30.0 min game time (steady-state window 25.0 min), wall time 11.1 s, Factorio 2.1.23.
Built 507/507 entities, 1 electric network(s).

## Legendary output per hour
- copper-plate: 818
- plastic-bar: 146
- steel-plate: 113
- low-density-structure: 43

## Machine utilisation
| machine | recipe | working | main stalls |
|---|---|---|---|
| foundry | casting-low-density-structure@epic | 27% | missing item input 73% |
| foundry | casting-low-density-structure@normal | 99% | missing item input 1% |
| foundry | casting-low-density-structure@rare | 42% | missing item input 58% |
| foundry | casting-low-density-structure@uncommon | 88% | missing item input 12% |
| recycler | - | 86% | no input 14% |

## Growing stock (containers)
| item | start | end | per hour |
|---|---|---|---|
| copper-plate@legendary | 23 | 362 | +814 |
| plastic-bar@legendary | 3 | 64 | +146 |
| copper-plate@uncommon | 21 | 76 | +132 |
| steel-plate@legendary | 2 | 49 | +113 |
| copper-plate@rare | 18 | 33 | +36 |
| steel-plate@uncommon | 2 | 16 | +34 |
| low-density-structure@normal | 16 | 29 | +31 |
| plastic-bar@uncommon | 5 | 17 | +29 |
| steel-plate@normal | 12 | 23 | +26 |
| copper-plate@epic | 5 | 9 | +10 |
| steel-plate@rare | 2 | 6 | +10 |
| plastic-bar@rare | 0 | 3 | +7 |
| low-density-structure@epic | 0 | 2 | +5 |
| low-density-structure@uncommon | 4 | 6 | +5 |
| steel-plate@epic | 0 | 2 | +5 |
| plastic-bar@epic | 0 | 1 | +2 |

## Machines stalled more than half the time
- foundry at (29.5, -4.5) casting-low-density-structure@rare: working 42%, mostly missing item input
- foundry at (34.5, -4.5) casting-low-density-structure@epic: working 26%, mostly missing item input
