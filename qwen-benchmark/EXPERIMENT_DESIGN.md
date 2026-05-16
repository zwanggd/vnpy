# Qwen3.6-35B-A3B 本地部署最优配置实验

## 1. 背景与目标

### 1.1 动机

在量化交易场景中，需要对大量金融新闻进行情感/方向分类（positive / negative / neutral）。当前方案使用 DeepSeek v4-pro API 远程调用，虽速度快（4.9s/条），但存在成本高、数据隐私、网络依赖等问题。因此探索本地部署 Qwen3.6-35B-A3B（MOE 架构，激活参数仅 3B，适合消费级硬件）的可行性。

### 1.2 实验目标

1. **找出 M3 Pro 36GB 上 llama.cpp 运行 Qwen3.6-35B-A3B 的最优配置**（吞吐、延迟、资源利用率的最优平衡）
2. **理解 M3 Pro 的性能边界**：GPU 利用率、内存带宽、并发能力
3. **建立可复现的 benchmark 框架**，用于未来模型/硬件对比

### 1.3 主要优化方向

1. **量化级别**：Q4_K_M（当前）→ 探索 Q3_K_M、Q5_K_M、IQ4 等
2. **上下文长度**：-c 参数对显存/内存占用和推理速度的影响
3. **批处理/并发**：-parallel 与 -b 参数组合
4. **Flash Attention**：-fa 开关对长上下文的影响
5. **KV Cache 配置**：cache-type（f16/q8_0/q4_0）和 cache-reuse
6. **GPU 层数**：-ngl 全部 offload vs 部分 offload

---

## 2. 硬件与环境

| 项目 | 详情 |
|------|------|
| **设备** | MacBook Pro M3 Pro |
| **内存** | 36GB 统一内存 |
| **CPU** | Apple M3 Pro（6P + 6E 核心） |
| **GPU** | 18 核 Apple GPU |
| **推理框架** | llama.cpp (via lmstudio-community build) |
| **模型** | Qwen3.6-35B-A3B-GGUF（MOE，总参数 35B，激活 3B） |

---

## 3. 模型信息

| 项目 | 详情 |
|------|------|
| **模型名称** | Qwen3.6-35B-A3B |
| **架构** | Mixture of Experts (MOE) |
| **总参数** | 35B |
| **激活参数** | ~3B per token |
| **GGUF 文件** | `Qwen3.6-35B-A3B-Q4_K_M.gguf` |
| **来源** | lmstudio-community |
| **上下文长度** | 原生 128K（本实验使用 4096） |

---

## 4. 基线配置与结果

### 4.1 当前 llama.cpp 启动参数

```bash
./llama-server \
  -m models/lmstudio-community/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf \
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
```

### 4.2 基线结果（50 条宁德时代新闻）

| 指标 | DeepSeek v4-pro (API) | Qwen3.6 (thinking OFF) |
|------|----------------------|------------------------|
| **成功率** | 100% | 100% |
| **单条耗时** | 4.9s | 11.9s（2.4x） |
| **4 workers 吞吐** | — | 4 × 11.9s 并发 = 0.34 req/s |
| **输出 token** | 114 avg | 128 avg（+12%） |
| **Think 块** | 0 | 0 |

**方向分布一致性（高）**：

| 方向 | DeepSeek | Qwen |
|------|----------|------|
| neutral | 34 | 33 |
| positive | 13 | 14 |
| negative | 3 | 3 |

### 4.3 基线结论

- Qwen 在分类准确性上与 DeepSeek v4-pro 高度一致
- 主要瓶颈是延迟（2.4x），34 req/s 远低于生产需求
- 输出略长（+12%），可能通过 prompt 优化减少

---

## 5. 实验设计

### 5.1 核心原则

1. **固定数据**：同一批 50 条宁德时代新闻，每个配置跑 3 轮
2. **固定推理参数**：temperature=0, top_p=1, max_tokens 固定, stream=ON
3. **单一变量**：每次只改一个参数，其余保持基线值
4. **可复现**：所有配置和结果记录在 `results/` 目录

### 5.2 测试数据集

| 项目 | 详情 |
|------|------|
| **数据来源** | 独立 SQLite 数据库 |
| **内容** | 宁德时代（CATL）相关新闻 |
| **数量** | 50 条（随机选取） |
| **字段** | title, content, publish_time |

### 5.3 每条请求记录

```json
{
  "request_id": "uuid",
  "config_id": "baseline_q4km",
  "round": 1,
  "input_tokens": 245,
  "output_tokens": 128,
  "total_latency_ms": 11900,
  "ttft_ms": 320,
  "tokens_per_second": 10.8,
  "label": "neutral",
  "confidence": 0.85,
  "json_parse_success": true,
  "error": null,
  "worker_id": 2,
  "timestamp": "2026-05-15T10:30:00Z"
}
```

### 5.4 汇总指标

| 指标 | 说明 |
|------|------|
| **avg latency** | 平均端到端延迟 |
| **p50 / p90 / p99 latency** | 延迟分位数 |
| **throughput (req/s)** | 吞吐量 |
| **avg output tokens** | 平均输出 token 数 |
| **avg tokens/s** | 生成速度 |
| **label distribution** | neutral/positive/negative 分布 |
| **label agreement** | 与 DeepSeek baseline 的一致率 |
| **JSON parse success rate** | JSON 解析成功率 |

---

## 6. 待测试的配置维度

### 6.1 量化级别（模型文件替换）

| 配置 ID | GGUF 量化 | 预期模型大小 | 预期影响 |
|---------|----------|-------------|---------|
| `q3km` | Q3_K_M | ~16GB | 更快但可能掉精度 |
| `q4km` | Q4_K_M（基线） | ~20GB | 当前基线 |
| `q5km` | Q5_K_M | ~24GB | 精度 vs 速度 |
| `iq4xs` | IQ4_XS | ~18GB | IQ 系列，声称更好的质量/大小比 |

### 6.2 上下文长度

| 配置 ID | -c 值 | 预期影响 |
|---------|-------|---------|
| `ctx2048` | 2048 | 更少内存，更快 prefill |
| `ctx4096` | 4096（基线） | 当前设置 |
| `ctx8192` | 8192 | 更长上下文，测试是否成为瓶颈 |
| `ctx16384` | 16384 | 探索上限 |

### 6.3 批处理大小

| 配置 ID | -b / -ub | 预期影响 |
|---------|---------|---------|
| `batch512` | 512 | 更小批次，更快 TTFT |
| `batch1024` | 1024 | 中等 |
| `batch2048` | 2048（基线） | 当前设置 |
| `batch4096` | 4096 | 更大批次，更高吞吐但可能更慢 TTFT |

### 6.4 Flash Attention

| 配置 ID | -fa | 预期影响 |
|---------|-----|---------|
| `fa_on` | on（基线） | 当前设置 |
| `fa_off` | off | 对比 FA 的实际收益 |

### 6.5 KV Cache 类型

| 配置 ID | cache-type-k/v | 预期影响 |
|---------|---------------|---------|
| `cache_f16` | f16 | 更高精度，更多内存 |
| `cache_q80` | q8_0（基线） | 当前设置 |
| `cache_q40` | q4_0 | 更少内存，可能质量下降 |

### 6.6 GPU 层数

| 配置 ID | -ngl | 预期影响 |
|---------|------|---------|
| `ngl99` | 99（基线） | 全部 GPU offload |
| `ngl80` | 80 | 部分 offload，测试是否全 GPU 已饱和 |
| `ngl60` | 60 | 更多 CPU 推理 |

### 6.7 并发 Workers

| 配置 ID | --parallel | 预期影响 |
|---------|-----------|---------|
| `par1` | 1 | 单请求 |
| `par4` | 4（基线） | 当前设置 |
| `par8` | 8 | 更高并发 |

---

## 7. 实验执行步骤

### Phase 1：建立基准线（1 轮）

1. 用基线配置跑 50 条 × 3 轮，确认结果可复现
2. 建立结果存储格式（SQLite / JSON Lines）
3. 编写自动化测试脚本

### Phase 2：逐维度扫描（约 20 个配置）

按优先级测试：
1. **量化级别**（4 个配置）—— 最大影响
2. **批处理大小**（4 个配置）
3. **并发数**（3 个配置）
4. **上下文长度**（4 个配置）
5. **KV Cache**（3 个配置）
6. **Flash Attention**（2 个配置）
7. **GPU 层数**（3 个配置）

### Phase 3：组合最优参数

基于 Phase 2 结果，组合多个最优参数进行最终验证。

### Phase 4：总结报告

生成包含以下内容的报告：
- 各维度的 latency-throughput-quality trade-off 曲线
- 最优配置推荐（生产环境 vs 开发环境）
- M3 Pro 36GB 性能边界分析

---

## 8. 目录结构

```
qwen-benchmark/
├── EXPERIMENT_DESIGN.md    # 本文件
├── configs/                # 各配置的启动参数
│   ├── baseline_q4km.sh
│   ├── q3km.sh
│   ├── q5km.sh
│   └── ...
├── scripts/                # 测试脚本
│   ├── run_benchmark.py    # 主测试脚本
│   ├── analyze_results.py  # 结果分析
│   └── config_manager.py   # 配置管理
├── results/                # 实验结果
│   ├── baseline_q4km/
│   │   ├── round_1.jsonl
│   │   ├── round_2.jsonl
│   │   └── round_3.jsonl
│   └── ...
└── reports/                # 分析报告
    └── final_report.md
```

---

## 9. 关键问题待确认

1. **量化文件获取**：Q3_K_M、Q5_K_M、IQ4_XS 的 GGUF 文件是否已下载？
2. **测试脚本**：是否已有可用的 Python 测试脚本（调用 llama.cpp server API）？
3. **Prompt 模板**：当前使用的 system prompt 和 user prompt 模板是什么？是否需要随配置变化？
4. **优先级**：先跑量化级别对比，还是先跑并发/批处理优化？
