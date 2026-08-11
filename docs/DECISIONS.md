# Project Decisions

本文只记录会长期影响项目方向、架构边界或分析语义的重要决策及其原因，不记录普通函数级改动。

## 2026-08 — V2 data layer remains isolated from V1

**Decision:** V2 猪周期 SQLite 与 V1 `stock_analysis.db` 保持隔离，V2 数据层暂不接入 V1 DatabaseManager。

**Why:** 产业数据具有独立的日期、来源、修订和更新频率语义。保持隔离可以避免基础数据建设与股票分析系统耦合，也确保分析模型变化不会破坏 V1 稳定路径。

**Status:** Active

## 2026-08 — Official-first, low-request and traceable acquisition

**Decision:** 数据入口优先选择官方、公开、稳定、可追溯且请求成本低的文件、正式 API 或已知 URL；必要发现必须受硬请求预算约束。

**Why:** 该策略兼顾数据可靠性、合规与安全风险、对官方服务器友好以及个人项目的长期维护成本。项目不进行全站扫描、高频并发、无限重试或限制绕过。

**Status:** Active

## 2026-08 — Persist processed sources and known state

**Decision:** 使用独立 `processed_sources` 和 known-state 读取，长期记住成功处理过的官方 URL，并将来源记忆与当前有效业务记录分开。

**Why:** 当前业务记录可能被新修订 URL 替换，但旧 URL 仍不应被遗忘。独立来源记忆可以避免重复访问，支持增量更新，并允许同一业务日期的新修订进入持久化判断。

**Status:** Active

## 2026-08 — Snapshot v0 is a visibility layer

**Decision:** V2 Data Snapshot v0 只展示本地 SQLite 已保存的数据，不输出周期阶段、股票结论或投资建议。

**Why:** 首先需要验证官方数据、持久化、来源追溯和长期数据库链路确实工作。单个时点的数据不足以形成周期或投资结论，不能用可见性里程碑替代分析层。

**Status:** Active

## 2026-08 — Cycle assessment requires multiple indicators

**Decision:** 周期判断不得依赖单一指标或单个时点。

**Why:** 能繁母猪、仔猪、生猪、猪粮比和成本指标反映不同时间尺度与传导环节。它们可能领先、滞后或互相矛盾，单指标容易造成误判，而矛盾本身也可能具有分析价值。

**Status:** Active

## 2026-08 — Six stages are a candidate interpretation framework

**Decision:** 下行、产能去化、底部形成、上行、高景气 / 扩产和顶部风险六阶段，只作为 v0.x 候选解释语言。

**Why:** 阶段边界、确认窗口和迁移条件仍需历史校准。未来允许合并、拆分、重新定义、调整权重，或改为得分制和阶段概率。

**Status:** Candidate

## 2026-08 — Separate industry, company and market layers

**Decision:** 产业周期、公司盈利和市场定价必须分层分析。

**Why:** 行业改善不代表所有公司盈利相同；公司还受销售价格、完全成本、出栏、效率和业务结构影响。股票也可能提前反映基本面，因此产业结论不能直接转换成个股结论。

**Status:** Active

## 2026-08 — Models may evolve without rebuilding the data layer

**Decision:** 分析架构必须允许调整时间窗口、阈值、权重和阶段模型，而不重建官方数据采集、来源追溯和 SQLite 存储。

**Why:** 分析方法需要随着历史验证持续迭代，但可靠的原始事实、日期语义和来源记录应保持稳定。把模型与数据基础解耦可以降低试错成本并保留可复现性。

**Status:** Active

## 2026-08 — Durable project reasoning belongs in Markdown

**Decision:** 重要的长期方向、分析框架变更和关键设计理由必须记录在仓库 Markdown 中。

**Why:** 聊天记录不是可靠的长期项目记忆。仓库文档可以让后续维护者或新的 ChatGPT/Codex 会话恢复上下文，并理解决策背后的原因，而不只是看到最终代码。

**Status:** Active

## 2026-08 — Historical calibration must be point-in-time

**Decision:** 历史校准和回测只能使用判断时点已经正式发布、当时可获得的数据，并区分业务所属日期、官方发布日期和后续修订。

**Why:** 使用后来发布或修订的数据会产生前视偏差，美化历史判断。现有 `publish_date`、`source_url` 和 processed source 语义应成为未来 as-of 分析的基础。

**Status:** Active

## 2026-08 — Analysis may abstain when evidence is insufficient

**Decision:** 当历史窗口不足、关键指标缺失、来源冲突或支持与反向证据接近时，模型可以不输出确定阶段，改为“证据不足”“低置信度”或“指标冲突”。

**Why:** 强制分类会制造虚假确定性。保留不确定性和来源口径，比为每个观测期生成标签更符合可解释、可追溯的分析原则。

**Status:** Active
