#!/bin/bash
# Baseline configuration for Qwen3.6-35B-A3B on M3 Pro 36GB
# This is the config that achieved 100% success rate on 50 CATL news items
# Latency: 11.9s avg per item (2.4x vs DeepSeek v4-pro API at 4.9s)

MODEL_PATH="./models/lmstudio-community/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf"

./llama-server \
  -m "${MODEL_PATH}" \
  -c 4096 \
  -ngl 99 \
  -fa on \
  -b 2048 \
  -ub 2048 \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --parallel 4 \
  --cache-reuse 256 \
  --ctx-checkpoints 32 \
  --cache-ram 8192 \
  --host 127.0.0.1 \
  --port 8080 \
  --reasoning off
