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

## 2026-08 — Trend features are a pure mechanical layer

**Decision:** `src/pig_cycle/trend.py` 作为 Fact Layer 与未来 Cycle Layer 之间的独立纯计算层，只接收领域记录并返回 frozen `NumericTrendFeatures`；不访问 SQLite、HTTP 或 LLM，也不输出周期阶段、置信度、阈值或投资信号。

**Why:** 机械数值特征需要可复用、透明且可独立验证，同时必须与事实存储和周期解释解耦，避免尚未校准的分析假设污染可靠数据层。

**Status:** Active

## 2026-08 — Whole-window direction and terminal streak are distinct

**Decision:** Snapshot 的“所示记录方向”继续表示整个展示窗口全部相邻变化的符号形态；Trend 的 `latest_streak_direction` 和 consecutive count 只表示序列末端连续同方向的相邻变化次数。两者必须分别命名和解释，不能互相替换。

**Why:** 一个窗口可以整体为“混合”，同时末端连续下降且首尾累计仍上涨。这些结论描述不同时间结构，强行合并会丢失信息并制造语义冲突。streak count 也不得解释为记录条数、周数或月数。

**Status:** Active

## 2026-08 — Keep current effective tables and add separate revision history

**Decision:** 保留以 `collection_date` 和 `(month, source_type)` 为业务键的 current effective tables，继续服务 Snapshot、current Trend 和日常流程；使用独立 append-only tables 保存 MOA weekly 与 sow monthly 的完整 revisions，而不把 current tables 改造成 multi-version tables。

**Why:** 这是对现有读取和日常流程破坏最小的方案，并允许 historical as-of、calibration 和未来 backtest 的版本语义独立演进。revision 表示具体官方 payload/version，首次观察时的 save status 只描述相对于当时 current state 的处理结果，不扩展为通用 event-sourcing。normal save 已将 processed/current/revision evidence 原子提交；current reader 仍读取 current effective tables，尚未切换到 revision replay。

**Status:** Active; point-in-time readers pending

## 2026-08 — Point-in-time distinguishes official availability from system knowledge

**Decision:** 未来 point-in-time reader 必须区分 official-availability as-of（按官方 `publish_date`）与 system-knowledge as-of（按首次成功观察的 `observed_at` 和历史处理顺序）。业务所属日期、官方发布时间和系统观察时间必须分别保存，不得互相冒充。

**Why:** 历史页面可能在官方发布多年后才被系统回填。只按发布日期可以研究理论可获得信息，但不能描述自动化系统当时实际知道什么。现有 Trend `as_of` 仅过滤传入 current records 的发布日期，不能恢复旧 revision。baseline import 必须保留来源标记和真实观察证据；同 URL 原地修订目前也可能因永久 URL 去重而无法自动发现。

**Status:** Active contract; readers pending

## 2026-08 — Baseline exact-payload time uses current updated_at

**Decision:** baseline revision 的 `observed_at` 优先使用通过校验的 `current.updated_at`；它必须可解析、timezone-aware、UTC offset 为 0 且不晚于本次 `imported_at`。不可用时回退到 baseline import time，不使用 `created_at`、`publish_date` 或 `processed_at` 猜测 exact-payload system knowledge。

**Why:** `current.updated_at` 只在当前 effective payload 真正 INSERT/UPDATE 时刷新，而 `processed_at` 仅证明 URL 首次成功登记。direct save 允许同 URL、同业务键的 changed payload 后续进入状态机，因此旧 `processed_at` 不能证明后来 exact payload 当时已经存在，否则 system-knowledge replay 会产生前视偏差。

**Status:** Active

## 2026-08 — Processed sources are baseline provenance evidence, not payload time

**Decision:** baseline preflight 使用 `processed_sources` 检查 URL、业务键、来源类型、发布日期和处理时间的 mapping/provenance consistency；mapping 矛盾可阻断，缺失或时间异常作为 warning，但 `processed_at` 不决定 baseline exact-payload `observed_at`。

**Why:** `processed_sources` 不保存完整 payload 或 fingerprint，无法建立 URL 首次登记时间与 current exact payload 之间的版本等价关系。

**Status:** Active

## 2026-08 — Baseline completion requires replay coverage, not row counts

**Decision:** baseline `complete` 必须逐 current business key 验证同 source URL、同 production fingerprint、完整 payload、合法 `sets_current` seed，并按 `observed_at ASC, revision_id ASC` replay 后与 current state 一致；revision/current 数量相等不能证明完成。

**Why:** 同一业务键可存在多个 revision，MOA fingerprint 又刻意排除本地派生的 `derived_pig_corn_ratio`。只有 full-payload replay invariant 才能证明 future point-in-time reader 拥有可靠起点。

**Status:** Active

## 2026-08 — Production revision activation requires an audited baseline gate

**Decision:** 正式库启用 revision-aware writes 前，必须停止 writer、备份并验证数据库、显式初始化 revision schema、执行只读 preflight、人工审阅问题与 fallback、在单个事务中 bootstrap、完成 post-write audit 和第二次幂等 audit；只有逐 current coverage 完整后才能解除 gate。

**Why:** revision 能力已在代码中实现，但正式库尚未写入 baseline。先写入新的 current update 会让既有 current state 缺少可靠 replay seed；单事务和双重审计可避免部分迁移或把“可写”误当成“已完成”。

**Status:** Active gate; production baseline pending
