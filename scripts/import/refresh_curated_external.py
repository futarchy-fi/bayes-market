#!/usr/bin/env python3
"""Curate, live-refresh from Manifold API, and emit clean external seeds,
anchors, and causal bridge proposals.

All selected markets are verified live via https://api.manifold.markets/v0/market/{ref}:
  - unresolved (isResolved == False)
  - future deadline (closeTime > TODAY)
  - non-degenerate probability (0.03 <= p <= 0.94)
  - 100% bridged into the FTM Bayesian Network (zero singletons)
  - strictly forward-in-time / same-year parent (parent.year <= child.year)
  - clean formatting (no double periods '..', no '?.' artifacts, no Greek 'ΑI')

Run from repo root:
  python3 scripts/import/refresh_curated_external.py \
      --ftm /tmp/seeds_ftm_v2.json \
      --prev-external backend/seeds_external.json \
      --out-external backend/seeds_external.json \
      --out-anchors scripts/import/data/anchors.json \
      --out-proposals scripts/bridge/data/bridge_proposals_remapped.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bridge"))
from apply_bridges import (  # noqa: E402
    extract_child_deadline_year,
    extract_var_year,
    logit,
    sigmoid,
)

TODAY = "2026-11-23"
UA = "bayes-market-curated-refresh/2.0 (futarchy.ai)"
LIQUIDITY = 10000.0

# Curated high-signal unresolved 2027+ AI-futures Manifold markets:
# (marketId, manifold_ref, ftm_parent_var, sign (+1/-1), strength (3..5), rationale)
CURATED_MARKETS: list[tuple[str, str, str, int, int, str]] = [
    # --- 1. Canonical AGI Timelines (2028..2048) ---
    ("x0067", "HQObM8ZeuU0YQ3HUdGZ2", "ftm_sub_agi_by_2027", +1, 5,
     "Direct AGI timeline anchor before 2028; Sub-AGI by 2027 strongly raises pre-2028 AGI probability."),
    ("x0071", "vbFbnc7bl8Q6CTPtG3FG", "ftm_sub_agi_by_2028", +1, 5,
     "Direct AGI timeline anchor before 2029; Sub-AGI by 2028 strongly raises pre-2029 AGI probability."),
    ("x0069", "hh2bXhwKDTioZ7KtGKfC", "ftm_sub_agi_by_2029", +1, 5,
     "Direct AGI timeline anchor before 2030; Sub-AGI by 2029 strongly raises pre-2030 AGI probability."),
    ("x0078", "MeHUMy1sKoFiz1OHr1FU", "ftm_agi_by_2030", +1, 5,
     "Direct AGI timeline anchor before 2031; meeting FTM AGI training threshold by 2030 maps directly."),
    ("x0074", "YvayfreXRtBvubSPKgmm", "ftm_agi_by_2031", +1, 5,
     "Direct AGI timeline anchor before 2032; meeting FTM AGI training threshold by 2031 maps directly."),
    ("x0086", "u0ZzZg3x5uD36Du0eDAZ", "ftm_agi_by_2032", +1, 5,
     "Direct AGI timeline anchor before 2033; meeting FTM AGI training threshold by 2032 maps directly."),
    ("x0088", "2g6qGs45XbbwbC0BJ1g8", "ftm_agi_by_2033", +1, 5,
     "Direct AGI timeline anchor before 2034; meeting FTM AGI training threshold by 2033 maps directly."),
    ("x0085", "5M7F5ApF8SH9osu8DGJb", "ftm_agi_by_2034", +1, 5,
     "Direct AGI timeline anchor before 2035; meeting FTM AGI training threshold by 2034 maps directly."),
    ("x0096", "phUWCiU3O3qaCmkMXb6y", "ftm_agi_by_2035", +1, 5,
     "Direct AGI timeline anchor before 2036; meeting FTM AGI training threshold by 2035 maps directly."),
    ("x0116", "WD1VD4NMaaRG1ouof9LP", "ftm_agi_by_2037", +1, 5,
     "Direct AGI timeline anchor before 2038; meeting FTM AGI training threshold by 2037 maps directly."),
    ("x0103", "srlaR1wDLUCU8lej269R", "ftm_agi_by_2039", +1, 5,
     "Direct AGI timeline anchor before 2040; meeting FTM AGI training threshold by 2039 maps directly."),
    ("x0153", "kaRBQKvUDqdJLIdP0Y7n", "ftm_agi_by_2041", +1, 5,
     "Direct AGI timeline anchor before 2042; meeting FTM AGI training threshold by 2041 maps directly."),
    ("x0146", "MowtNfp5FkGicxbzsgcb", "ftm_agi_by_2044", +1, 5,
     "Direct AGI timeline anchor before 2045; meeting FTM AGI training threshold by 2044 maps directly."),
    ("x0114", "gydlA7gBnOlkzqYd67Wt", "ftm_agi_by_2045", +1, 5,
     "Direct AGI timeline anchor before 2048; meeting FTM AGI training threshold by 2045 maps directly."),

    # --- 2. AGI Architecture, Pathway & Anti-Progress Signals ---
    ("x0246", "IdQPxWoEENJyu8NvHR9u", "ftm_auto_rnd_t0_by_2027", +1, 4,
     "Early R&D automation crossing 5% by 2027 strongly raises likelihood of a 2027 AGI fire alarm."),
    ("x0084", "ia45vPl7XunfCIclcIfY", "ftm_agi_by_2035", +1, 4,
     "Reaching AGI training compute by 2035 strongly favors current LLM scaling paradigm succeeding."),
    ("x0139", "MqHJpapTs2Mu1BvyLGiG", "ftm_agi_by_2035", +1, 4,
     "Faster AGI arrival (by 2035) makes it much more likely the first AGI is built on LLMs."),
    ("x0102", "dq71tp00zu", "ftm_agi_by_2035", +1, 3,
     "Reaching AGI by 2035 favors incumbent API-model labs rather than a new post-paradigm entrant."),
    ("x0072", "389HpvdvigElXaLZ6ZYH", "ftm_agi_by_2035", -1, 4,
     "Reaching AGI by 2035 makes an intervening AI winter substantially less likely."),
    ("x0261", "8yFaXVxy1qQ5RzfVIxtj", "ftm_sub_agi_by_2029", -1, 4,
     "Reaching Sub-AGI by 2029 makes OpenAI abandoning its AGI goal before 2030 much less likely."),

    # --- 3. ASI & Takeoff Speed ---
    ("x0142", "wscxt4zLBfJ3DWYzrPaU", "ftm_sub_agi_by_2027", +1, 5,
     "Pre-2028 ASI requires crossing weakly general AI capability by 2027."),
    ("x0129", "A98kMucU2mO94nOyiLxN", "ftm_sub_agi_by_2028", +1, 5,
     "Pre-2029 ASI is strongly driven by reaching Sub-AGI by 2028."),
    ("x0099", "bef64nPBEaB8w2dZsdfH", "ftm_sub_agi_by_2029", +1, 5,
     "Pre-2030 ASI is strongly driven by reaching Sub-AGI by 2029."),
    ("x0133", "Sv27vdqyFogBh5ZVfucJ", "ftm_agi_by_2031", +1, 5,
     "Pre-2032 ASI is strongly driven by meeting AGI training compute requirements by 2031."),
    ("x0154", "Nc9T6yrdpUP6D2LAJobb", "ftm_agi_by_2033", +1, 5,
     "Pre-2034 ASI is strongly driven by meeting AGI training compute requirements by 2033."),
    ("x0218", "toouubbjmj", "ftm_agi_by_2035", +1, 5,
     "Pre-2036 ASI is strongly driven by meeting AGI training compute requirements by 2035."),
    ("x0073", "F3WW5VQthbykdojxr0Ef", "ftm_agi_by_2030", +1, 5,
     "Superintelligence by 2030 (conditional on survival) closely tracks AGI compute sufficiency by 2030."),
    ("x0070", "cSmn5bvykckNzpKJYz1a", "ftm_agi_by_2040", +1, 5,
     "Superintelligence by 2040 (conditional on survival) closely tracks AGI compute sufficiency by 2040."),
    ("x0092", "tvoPGB4JP7wbV0dN1iYq", "ftm_agi_by_2045", +1, 5,
     "Superintelligence by 2050 closely tracks reaching AGI compute sufficiency by 2045."),
    ("x0209", "NCKfrEGePme7MPrZa3jK", "ftm_full_auto_rnd_by_2035", +1, 3,
     "Rapid full R&D automation by 2035 increases probability of a sharp recursive takeoff (<72h)."),

    # --- 4. AI R&D Automation, Math, Science & Benchmarks ---
    ("x0354", "IgN0uNOzzS", "ftm_auto_rnd_t0_by_2027", +1, 5,
     "Autonomous AI research by mid-2027 directly tracks FTM R&D task automation in 2027."),
    ("x0273", "Dd6cIaOO5cHHZ6qjh59M", "ftm_auto_rnd_t0_by_2027", +1, 5,
     "Drop-in remote AI workers by end of 2027 directly aligns with 5%+ R&D automation by 2027."),
    ("x0252", "LFOo1OITz7nNdeWzvyP3", "ftm_auto_rnd_t2_by_2030", +1, 5,
     "AI surpassing humans in scientific research by 2030 tracks 50% R&D automation by 2030."),
    ("x0215", "35y62f0OyIK7pTsVoifT", "ftm_auto_rnd_t1_by_2029", +1, 4,
     "AI-generated papers at top ML conferences by 2030 tracks 20% R&D automation by 2029."),
    ("x0174", "p0fzp3jqqc", "ftm_sub_agi_by_2029", +1, 4,
     "Claiming the ARC-AGI Grand Prize before 2030 tracks broad generalization (Sub-AGI) by 2029."),
    ("x0256", "uyCcw5fmUYcW3WAyddHZ", "ftm_sub_agi_by_2030", +1, 4,
     "An LLM claiming ARC-AGI is boosted by reaching Sub-AGI by 2030 on the current paradigm."),
    ("x0093", "OO8ROn5CIq", "ftm_auto_rnd_t1_by_2029", +1, 4,
     "Superhuman math problem-solving before 2030 tracks 20% R&D automation by 2029."),
    ("x0353", "AynyL0t2g2", "ftm_auto_rnd_t1_by_2030", +1, 4,
     "10M-line Lean mathlib by 2030 tracks AI-accelerated formal R&D automation (20% by 2030)."),
    ("x0300", "Cxo1aXMF2iuvoul2FAhf", "ftm_agi_by_2040", +1, 3,
     "Resolving P vs NP by 2050 is substantially more likely if AGI is achieved by 2040."),
    ("x0282", "9AynNtnO5I", "ftm_auto_rnd_t0_by_2027", +1, 3,
     "Sub-10-minute Minecraft RSG before 2028 reflects agentic capability progress tracked by 2027 R&D automation."),
    ("x0094", "G0GmOyaD1Qx3LoXfP9N7", "ftm_sub_agi_by_2034", +1, 4,
     "Arbitrary open-world Minecraft task competence before 2035 tracks Sub-AGI by 2034."),
    ("x0275", "HS8ndzFminW0UN2kRDgq", "ftm_auto_rnd_t0_by_2028", +1, 4,
     "Human-level play across randomly selected video games in 2028 tracks broad AI progress by 2028."),
    ("x0115", "q6s2ZQIIII", "ftm_auto_rnd_t0_by_2027", +1, 3,
     "Mechanistic interpretability of GPT-2 by 2028 is accelerated by automated AI R&D in 2027."),
    ("x0360", "EN2R0LLgn9", "ftm_sw_ratio_t1_by_2035", +1, 3,
     "LLM beating a chess super-grandmaster by 2035 tracks 100x algorithmic software efficiency gains by 2035."),

    # --- 5. Compute, Datacenters, Scaling & Frontier Labs ---
    ("x0366", "mjESBbBZWK7PPkHQ0Ur6", "ftm_train_run_t2_by_2032", -1, 4,
     "Crossing 1e31 FLOP training runs by 2032 implies sustained frontier scaling, reducing odds of a 12-month SOTA pause."),
    ("x0399", "PLCQhQzUs6", "ftm_gwp_compute_t1_by_2029", +1, 3,
     "Compute investment exceeding 1% of GWP by 2029 boosts demand for alternative/space datacenter buildouts."),
    ("x0371", "ugRnhOtcqN", "ftm_gwp_compute_t0_by_2028", +1, 4,
     "OpenAI reaching $100B revenue in 2028 tracks global AI compute investment exceeding 0.5% of GWP by 2028."),
    ("x0333", "4i4y5ktv3n", "ftm_gwp_compute_t0_by_2027", +1, 3,
     "Rapid global compute investment (>0.5% GWP by 2027) enables new well-capitalized frontier labs before 2028."),
    ("x0151", "56gymfk8ma", "ftm_agi_by_2030", -1, 4,
     "Very early AGI/ASI by 2030 reduces the window for SSI to ship a commercial product before ASI."),
    ("x0214", "31TfDsy8jgAr4j9sHD6V", "ftm_sub_agi_by_2029", +1, 3,
     "Reaching Sub-AGI before 2030 heightens governance/commercialization tension inside frontier safety labs."),

    # --- 6. Macroeconomics, Labor, Automation & Media ---
    ("x0269", "zg7xJ5ZkJJ4wJPJDPjWO", "ftm_gwp_growth_max_t0_by_2027", +1, 5,
     "Visible US GDP/productivity trend break by 2028 directly corresponds to global growth exceeding 5%/yr by 2027."),
    ("x0281", "TryNuKNJXNdiYDCXRpPi", "ftm_auto_goods_t1_by_2029", +1, 5,
     "US unemployment exceeding 10% from AI before 2030 tracks 20% goods-and-services automation by 2029."),
    ("x0165", "pM0emIJkRESze9dQQyHe", "ftm_auto_goods_t2_by_2030", +1, 5,
     "AI-driven mass unemployment by 2030 tracks 50% goods-and-services automation by 2030."),
    ("x0344", "ddNCdrbzFtadsm5WUzqJ", "ftm_auto_goods_t2_by_2029", +1, 5,
     "Near-complete economic automation before 2030 strongly tracks 50% goods automation by 2029."),
    ("x0302", "LvVDGJAlWrYyk7qmyIqq", "ftm_full_auto_by_2034", +1, 5,
     "Near-complete economic automation before 2035 directly tracks FTM full goods automation by 2034."),
    ("x0291", "ap8fNwshZJN3HOBVQLu5", "ftm_full_auto_by_2045", +1, 5,
     "Full automation of >97% of jobs before 2075 tracks FTM full goods automation by 2045."),
    ("x0090", "kyxxpr56vv", "ftm_auto_goods_t0_by_2029", +1, 4,
     "AI becoming life-changing for the general public by end of 2029 tracks 5% goods automation by 2029."),
    ("x0380", "a5qjz7gClUTBF2QDMpQD", "ftm_auto_goods_t1_by_2030", +1, 4,
     "US UBI introduction by 2030 is strongly driven by 20% labor automation by 2030."),
    ("x0152", "OKiiNBPTnoyjVTxFqtws", "ftm_gwp_compute_t2_by_2032", +1, 3,
     "AI compute capex exceeding 2% of GWP by 2032 increases macroeconomic dislocation and crash risk."),
    ("x0347", "l694w77ahy", "ftm_auto_goods_t2_by_2040", +1, 4,
     "A one-person $1B company by 2040 tracks 50% goods-and-services automation by 2040."),
    ("x0267", "A319ydGB1B7f4PMOROL3", "ftm_auto_goods_t0_by_2028", +1, 4,
     "Prompt-to-full-movie generation in early 2028 tracks 5% goods-and-services automation by 2028."),
    ("x0345", "LGvGEKD3bbdS9uxFgmWJ", "ftm_auto_goods_t1_by_2029", +1, 4,
     "Prompt-to-high-quality video games before 2030 tracks 20% goods-and-services automation by 2029."),
    ("x0330", "eu3xUzwd3j9hsyS6IYk1", "ftm_auto_goods_t3_by_2040", +1, 4,
     "Majority AI-generated digital entertainment by 2040 tracks 90% goods-and-services automation by 2040."),
    ("x0251", "8LdjDDGtPYeHQbbTDCkj", "ftm_auto_goods_t1_by_2030", +1, 3,
     "Five AI-written NYT fiction bestsellers before 2031 tracks 20% economic task automation by 2030."),
    ("x0232", "xRKVaKdN6F2YBYneq7Jk", "ftm_agi_by_2040", +1, 4,
     "Achieving AGI by 2040 gives a decade+ of post-AGI R&D to cure aging before 2050."),
    ("x0202", "NtqQ7bNiunP5aHWJamma", "ftm_auto_goods_t1_by_2028", -1, 4,
     "20% goods-and-services automation by 2028 makes benign near-term labor outcomes substantially less likely."),
    ("x0310", "FSAlCG0hY2tv3clI9NHm", "ftm_auto_goods_t2_by_2035", +1, 3,
     "50% goods-and-services automation by 2035 drives replacement of low-wage sweatshop manufacturing."),

    # --- 7. Robotics & Autonomous Vehicles ---
    ("x0289", "hdWDcQuy1aDtknfgZe64", "ftm_auto_goods_t0_by_2029", +1, 4,
     "Level-5 self-driving cars in a major US city before 2030 tracks 5% real-world task automation by 2029."),
    ("x0227", "92ObamYS7hVzmVRTYd5D", "ftm_auto_goods_t1_by_2030", +1, 4,
     "100k deployed humanoid robots by 2030 tracks 20% goods-and-services automation by 2030."),
    ("x0328", "4S1s9hug8VRQWFdwXwgy", "ftm_auto_goods_t2_by_2029", +1, 5,
     "Replacing >50% of human physical labor by robots before 2030 tracks 50% goods automation by 2029."),
    ("x0137", "wTnNfSRkPmKWmYSs1uND", "ftm_auto_goods_t1_by_2029", +1, 3,
     "Autonomous passenger aircraft piloting before 2030 tracks 20% goods-and-services automation by 2029."),
    ("x0197", "7DXAL229eyElYUannr94", "ftm_auto_goods_t3_by_2040", +1, 3,
     "Banning human-driven cars in a city center by 2040 tracks 90% goods-and-services automation by 2040."),

    # --- 8. AI Safety, Governance, Geopolitics & Catastrophic Risk ---
    ("x0077", "4fehtquIkz1RxcbJejDq", "ftm_sub_agi_by_2029", +1, 4,
     "AI escaping containment by 2029 is strongly raised if weakly general AI arrives by 2029."),
    ("x0241", "1gRl5hxC7wsYBoyRwfzJ", "ftm_sub_agi_by_2028", +1, 4,
     "Autonomous AI self-replication by end of 2028 tracks reaching Sub-AGI by 2028."),
    ("x0177", "qonVOPgTA6eIOFqhQ4ph", "ftm_sub_agi_by_2028", +1, 4,
     "A government 'Manhattan Project' for AGI before 2029 is triggered by rapid Sub-AGI progress by 2028."),
    ("x0104", "0YCYyjBNcZ2XW9Qer4sD", "ftm_sub_agi_by_2029", +1, 4,
     "US government takeover of OpenAI before 2030 is triggered by rapid pre-2030 Sub-AGI arrival."),
    ("x0208", "Uxu9dll7SdYVTGUEmebV", "ftm_agi_by_2035", +1, 4,
     "US/UK nationalization of frontier AI labs by 2035 tracks AGI arrival by 2035."),
    ("x0126", "dFx5xg9c4mcYSblxazwA", "ftm_sub_agi_by_2035", +1, 3,
     "25-nation unified AI development standards by 2035 are catalyzed by Sub-AGI arrival by 2035."),
    ("x0216", "RQAbCjnhmzVhODm7MVco", "ftm_agi_by_2035", -1, 4,
     "Reaching full AGI compute sufficiency by 2035 makes an effective global AI pause before 2035 less likely."),
    ("x0098", "nf4QhoSMOmoa9m5iLpDt", "ftm_agi_by_2037", -1, 4,
     "Reaching full AGI compute sufficiency by 2037 indicates US AI research was not banned beforehand."),
    ("x0212", "czck4zd672", "ftm_sub_agi_by_2029", +1, 4,
     "A massive AI-caused catastrophe before 2030 is strongly elevated by Sub-AGI arrival by 2029."),
    ("x0080", "3cBLGjcbZ2ElJkHCdDpm", "ftm_sub_agi_by_2029", +1, 4,
     "Catastrophic >20% population loss from AI before 2030 depends on crossing Sub-AGI by 2029."),
    ("x0265", "nrRwBalvp8XEsvS39Su0", "ftm_sub_agi_by_2028", +1, 4,
     "An AI disaster killing >=100k people before 2029 is strongly elevated by Sub-AGI by 2028."),
    ("x0225", "hMn7h6TFqzYZr16Lmtht", "ftm_agi_by_2039", +1, 4,
     "An AI disaster killing >=100 people before 2040 is strongly elevated by AGI arrival by 2039."),
    ("x0260", "hd6bCiYXPBI1pikaryWa", "ftm_agi_by_2032", +1, 4,
     "Very rapid strict AGI by 2032 compresses alignment lead-time and elevates pre-2040 1bn-death risk."),
    ("x0204", "T1uSdwfOr3pXN0V4rmsF", "ftm_agi_by_2040", +1, 4,
     "A misaligned-AI 'close call' before 2100 is substantially more likely if AGI arrives by 2040."),
    ("x0226", "OEkQx1xzABwnkQRKwyL9", "ftm_agi_by_2033", +1, 4,
     "Rapid strict AGI by 2033 leaves less time for alignment, raising misaligned-AGI takeover risk."),
    ("x0372", "B8w3FaPyQJWJslzSCTv5", "ftm_sub_agi_by_2033", +1, 4,
     "Superhuman persuasion before 2034 tracks reaching weakly general AI (Sub-AGI) by 2033."),
    ("x0132", "r37ICWFzACaZlXIJCEpp", "ftm_gwp_compute_t2_by_2034", +1, 4,
     "Compute investment exceeding 2% of GWP by 2034 turns megaclusters into strategic kinetic targets."),
    ("x0076", "RwF7zWPBVLYKlmTavXUh", "ftm_auto_goods_t1_by_2029", +1, 4,
     "20% goods-and-services automation by 2029 drives public backlash and 100k-person anti-AI protests."),
    ("x0268", "nOXCmJFNsLx08PjOc4Qk", "ftm_gwp_compute_t0_by_2028", +1, 3,
     "AI compute buildout exceeding 0.5% of GWP by 2028 elevates AI to a top-tier 2028 political issue."),
    ("x0270", "cNmTnf0Q0OqH2clJS26c", "ftm_auto_goods_t0_by_2027", +1, 4,
     "Instant deepfakes by end of 2027 tracks crossing 5% economic AI deployment by 2027."),
    ("x0108", "gRkJsEFMbvzqpICdcJxP", "ftm_sub_agi_by_2035", +1, 3,
     "Reaching Sub-AGI by 2035 raises likelihood of superhuman persuasion emerging ahead of superintelligence."),
    ("x0234", "9YEJjxtnXHFsbRe311cX", "ftm_sub_agi_by_2029", +1, 4,
     "An AI socially engineering its escape by 2029 is strongly raised by reaching Sub-AGI by 2029."),
    ("x0235", "IW3ACtIeEN8JTvUxR3fy", "ftm_sub_agi_by_2028", +1, 4,
     "US federal AI safety spending >0.1% of budget by 2028 is driven by rapid Sub-AGI progress by 2028."),
    ("x0170", "20VEF6SzC8Mzx4jS5TVR", "ftm_sub_agi_by_2028", +1, 3,
     "Early Sub-AGI progress by 2028 sustains a coherent organized AI safety movement in May 2029."),
    ("x0249", "TeWRQojLHpWs2EH05HcC", "ftm_agi_by_2035", +1, 4,
     "Faster AGI arrival by 2035 increases risk of deploying an unaligned AGI with existential consequences."),
    ("x0348", "MkeETzMpiLJ0JuoNqiZH", "ftm_agi_by_2040", +1, 4,
     "Reaching AGI by 2040 raises the probability of AI taking over governance/control by 2100."),
    ("x0240", "qRiKFHS6nvztSzdecHZo", "ftm_agi_by_2033", +1, 4,
     "Rapid AGI arrival by 2033 leaves less alignment buffer, elevating biological-extinction tail risk."),
]


def clean_title(raw: str) -> str:
    # Fix Greek Alpha typo, collapse ellipses/multi-spaces, strip outer whitespace
    s = raw.replace("\u0391I", "AI").replace("...", " ").strip()
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([?.!])", r"\1", s)
    return s


def slugify_var(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return "x_" + s[:64].rstrip("_")


def fetch_manifold_market(ref: str) -> dict:
    url = f"https://api.manifold.markets/v0/market/{ref}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def format_expires(close_ms: int | None) -> str:
    if not close_ms:
        return "2099-12-31T23:59:59Z"
    try:
        dt = datetime.fromtimestamp(close_ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return "2099-12-31T23:59:59Z"
    if dt.year > 2099:
        return "2099-12-31T23:59:59Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def choose_uncalibrated_cpt(p_child: float, p_parent: float, sign: int, strength: int) -> tuple[float, float]:
    """Choose (p_given_yes, p_given_no) in [0.02, 0.98] whose calibrated lift >= 0.14."""
    base_spread = {5: 3.0, 4: 2.4, 3: 2.0}.get(strength, 2.2)

    def calibrated_lift(spread: float) -> tuple[float, float, float]:
        # Initial rows with log-odds difference == sign * spread
        hi = min(max(sigmoid(+spread / 2.0), 0.02), 0.98)
        lo = min(max(sigmoid(-spread / 2.0), 0.02), 0.98)
        r_yes, r_no = (hi, lo) if sign > 0 else (lo, hi)
        # Bisect logit shift delta matching apply_bridges.py
        a, b = -14.0, 14.0
        for _ in range(60):
            mid = (a + b) / 2.0
            imp = p_parent * sigmoid(logit(r_yes) + mid) + (1.0 - p_parent) * sigmoid(logit(r_no) + mid)
            if imp > p_child:
                b = mid
            else:
                a = mid
        d = (a + b) / 2.0
        c_yes = sigmoid(logit(r_yes) + d)
        c_no = sigmoid(logit(r_no) + d)
        return r_yes, r_no, abs(c_yes - c_no)

    for spread in (base_spread, base_spread + 0.6, base_spread + 1.2, 4.2, 5.0, 6.0, 7.2):
        r_yes, r_no, lift = calibrated_lift(spread)
        if lift >= 0.14:
            return round(r_yes, 4), round(r_no, 4)
    r_yes, r_no, _ = calibrated_lift(7.2)
    return round(r_yes, 4), round(r_no, 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ftm", default="/tmp/seeds_ftm_v2.json")
    ap.add_argument("--prev-external", default="backend/seeds_external.json")
    ap.add_argument("--out-external", default="backend/seeds_external.json")
    ap.add_argument("--out-anchors", default="scripts/import/data/anchors.json")
    ap.add_argument("--out-proposals", default="scripts/bridge/data/bridge_proposals_remapped.json")
    args = ap.parse_args()

    ftm = json.loads(Path(args.ftm).read_text())
    ftm_by_var = {m["variableId"]: m for m in ftm["markets"].values()}

    prev_ext = {}
    if Path(args.prev_external).exists():
        prev_ext = json.loads(Path(args.prev_external).read_text()).get("markets", {})

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Live-fetching {len(CURATED_MARKETS)} curated Manifold markets at {now}...")

    fetched: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futs = {pool.submit(fetch_manifold_market, ref): (mid, ref) for mid, ref, *_ in CURATED_MARKETS}
        for fut in concurrent.futures.as_completed(futs):
            mid, ref = futs[fut]
            try:
                fetched[mid] = fut.result()
            except Exception as exc:
                print(f"WARN: failed to fetch {mid} ({ref}): {exc}")

    ext_markets: dict[str, dict] = {}
    anchors: list[dict] = []
    bridges: list[dict] = []
    used_vars: set[str] = set()
    skipped: list[tuple[str, str]] = []

    for mid, ref, parent_var, sign, strength, rationale in CURATED_MARKETS:
        raw = fetched.get(mid)
        if not raw:
            skipped.append((mid, "fetch failed"))
            continue
        if raw.get("isResolved"):
            skipped.append((mid, "already resolved"))
            continue
        if raw.get("outcomeType") != "BINARY":
            skipped.append((mid, f"non-binary ({raw.get('outcomeType')})"))
            continue
        p = raw.get("probability")
        if p is None or not (0.03 <= float(p) <= 0.94):
            skipped.append((mid, f"probability out of informative band [0.03, 0.94]: {p}"))
            continue
        p = round(float(p), 6)
        expires = format_expires(raw.get("closeTime"))
        if expires[:10] <= TODAY:
            skipped.append((mid, f"expired ({expires[:10]})"))
            continue
        if parent_var not in ftm_by_var:
            skipped.append((mid, f"missing FTM parent {parent_var}"))
            continue

        title = clean_title(raw.get("question") or prev_ext.get(mid, {}).get("title", ""))
        url = raw.get("url") or prev_ext.get(mid, {}).get("provenance", {}).get("url") or f"https://manifold.markets/market/{ref}"
        forecasters = int(raw.get("uniqueBettorCount") or 0)
        volume = round(float(raw.get("volume") or 0.0), 2)

        # Preserve prior variableId if unique and clean, else slugify
        prev_vid = prev_ext.get(mid, {}).get("variableId")
        vid = prev_vid if (prev_vid and prev_vid not in used_vars and "\u0391" not in prev_vid) else slugify_var(title)
        if vid in used_vars:
            vid = f"{vid}_{mid}"
        used_vars.add(vid)

        # Clean description: never emit '..' or '?.'
        title_term = title if title[-1:] in ".?!" else title + "."
        desc = (
            f"{title_term} Imported from Manifold ({url}); resolution follows the "
            f"source market's criteria. Live forecast as of {TODAY}: {p:.1%} "
            f"({forecasters} forecasters)."
        )
        assert ".." not in desc and "?." not in desc, f"Punctuation artifact in {mid}: {desc}"

        mkt = {
            "id": mid,
            "title": title,
            "description": desc,
            "variableId": vid,
            "status": "active",
            "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
            "marginals": {"yes": p, "no": round(1.0 - p, 6)},
            "liquidity": LIQUIDITY,
            "volume": 0.0,
            "created_at": now,
            "expires_at": expires,
            "provenance": {
                "source": "manifold",
                "ref": ref,
                "url": url,
                "method": "external-import-v2",
                "forecasters": forecasters,
                "sourceVolume": volume,
                "refreshedAt": now,
            },
            "anchor": {
                "source": "manifold",
                "ref": ref,
                "url": url,
                "value": p,
                "fetchedAt": now,
            },
        }

        # Verify causal year ordering before accepting
        py = extract_var_year(parent_var)
        cy = extract_child_deadline_year(mkt)
        if py is not None and cy is not None and py > cy:
            skipped.append((mid, f"backwards-in-time {parent_var} ({py}) > child ({cy})"))
            continue

        p_parent = ftm_by_var[parent_var]["marginals"]["yes"]
        r_yes, r_no = choose_uncalibrated_cpt(p, p_parent, sign, strength)
        # Double-check Bayes feasibility for lift >= 0.10
        max_possible = min(p / p_parent, (1 - p) / (1 - p_parent)) if sign > 0 else min(p / (1 - p_parent), (1 - p) / p_parent)
        if max_possible < 0.11:
            skipped.append((mid, f"Bayes lift ceiling {max_possible:.3f} < 0.11 (p={p:.3f}, parent={parent_var}@{p_parent:.3f})"))
            continue

        ext_markets[mid] = mkt
        anchors.append({
            "marketId": mid,
            "variableId": vid,
            "source": "manifold",
            "ref": ref,
            "url": url,
            "value": p,
            "fetchedAt": now,
        })
        bridges.append({
            "externalId": mid,
            "parents": [parent_var],
            "strength": strength,
            "direction": "positive" if sign > 0 else "negative",
            "cpt": {
                f"{parent_var}=yes": r_yes,
                f"{parent_var}=no": r_no,
            },
            "rationale": rationale,
        })

    Path(args.out_external).write_text(json.dumps({
        "version": "seeds-v1",
        "markets": ext_markets,
        "conditionalMarginals": {},
    }, indent=1) + "\n")

    Path(args.out_anchors).write_text(json.dumps({
        "builtAt": now,
        "anchors": anchors,
    }, indent=1) + "\n")

    Path(args.out_proposals).write_text(json.dumps({
        "builtAt": now,
        "bridges": bridges,
    }, indent=1) + "\n")

    print(f"Kept & refreshed: {len(ext_markets)} external markets, {len(anchors)} anchors, {len(bridges)} bridges.")
    if skipped:
        print(f"Skipped ({len(skipped)}):")
        for mid, reason in skipped:
            print(f"  - {mid}: {reason}")


if __name__ == "__main__":
    main()
