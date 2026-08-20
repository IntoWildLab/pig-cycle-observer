# Pig Cycle Observer — Project Context

## 1. 项目背景

`pig-cycle-observer`（猪周期观察）是一个面向个人学习和信息整理的猪周期观察项目。项目基于 MIT 许可的 `ZhuLinsen/daily_stock_analysis` 衍生，当前仓库由 IntoWildLab 个人化维护，与上游项目不存在官方合作、授权背书或隶属关系。

项目的核心用途是整理公开行情、新闻、官方猪周期数据和模型分析结果，并生成报告。所有内容仅供信息整理、技术学习和研究，不构成投资建议。

当前观察标的为：

| 代码 | 名称 |
| --- | --- |
| `002714` | 牧原股份 |
| `300498` | 温氏股份 |
| `000876` | 新希望 |
| `605296` | 神农集团 |
| `159867` | 鹏华中证畜牧养殖 ETF |

## 2. 代码结构

项目同时包含稳定的 V1 股票分析系统和正在建设的 V2 猪周期官方数据层。

### V1 主系统

- `main.py`：分析任务主入口。
- `server.py` / `api/`：FastAPI 服务。
- `src/core/`：分析主流程编排。
- `src/services/`：业务服务。
- `src/repositories/`：数据访问。
- `src/reports/`：报告生成。
- `data_provider/`：多行情数据源和 fallback。
- `bot/`：机器人入口。
- `apps/dsa-web/`：Web 工作台。
- `apps/dsa-desktop/`：Electron 桌面端。
- `scripts/run_daily.ps1`：Windows 正式交易日运行脚本，允许通知，不含 `--force-run`。
- `scripts/run_weekend_test.ps1`：周末/节假日测试脚本，使用 `--force-run --no-notify`。

V1 已包含股票行情、技术指标、新闻搜索、LLM 分析、报告、邮件通知、Web/桌面工作台和本地自动化。当前个人化环境主要使用 DeepSeek、Tavily、126 邮箱和 Windows 任务计划程序。

### V2 猪周期数据层

V2 代码独立放在 `src/pig_cycle/`，暂未接入 V1 daily pipeline、邮件或股票买卖信号。

- `moa_weekly.py`
  - 解析农业农村部周度畜产品和饲料价格。
  - 字段包括采集日、发布日、仔猪、生猪、玉米、豆粕、育肥猪饲料价格和派生猪粮比。
  - 区分历史回填和日常增量。
  - 历史回填上限：12 个列表页、60 篇文章、72 次 GET。
  - 日常增量固定最多 2 次 GET：首页列表 + 1 篇未知文章。
- `sow_monthly.py`
  - 定义能繁母猪月度数据模型。
  - 解析存栏、环比、同比、月末、季度末和跨年语义。
  - 2026 年正常保有量常量为 3750 万头。
  - 提供官方产能区间 `red_low / yellow_low / green / yellow_high / red_high`。
- `sow_official.py`
  - 对调用者给定的单一官方 URL 执行白名单校验和保守读取。
  - 支持 HTML、CSV、Excel 和 PDF 文本提取。
  - 只接受全国口径能繁母猪数据。
- `sow_discovery.py`
  - 从调用者给定的单一官方列表入口发现少量候选。
  - 单次最多 5 次请求、2 篇候选。
  - 不自动翻页，不做全站扫描。
- `storage.py`
  - 使用独立 SQLite 保存周度价格、月度母猪数据、已处理来源和 append-only revisions。
  - 提供原子 current/revision 写入、修订判断、纯本地 known-state 读取、revision baseline 审计和引导写入，以及 System-Knowledge as-of replay。
  - revision reader 和 normal save 均执行基于中国业务时间的 future-business integrity 校验。
- `coordinator.py`
  - 将本地 processed URL 记忆接入 MOA 周度日常增量流程。
  - 保持获取层和存储层职责分离，不增加 Step 1B 请求预算。
- `snapshot.py`
  - 从本地 SQLite 生成纯文本 V2 Data Snapshot v0。
  - 只展示已有数据，不进行周期判断或投资建议。
- `trend.py`
  - 位于事实层与未来周期判断层之间，使用纯函数把领域记录转换为透明、可复用的机械趋势特征。
  - 不访问 SQLite、HTTP 或 LLM；结果使用 frozen `NumericTrendFeatures`。
  - 当前支持 MOA 的仔猪、生猪、玉米和派生猪粮比，以及按单一 `SowSourceType` 隔离的能繁母猪存栏。
- `historical_trend.py`
  - 将 System-Knowledge reader 恢复的领域记录薄接到既有 Trend pure functions。
  - 提供 MOA 周度与按单一 `SowSourceType` 隔离的母猪历史趋势 API，不重复 revision replay 或业务时间校验。

对应离线测试位于：

- `tests/test_moa_weekly.py`：26 个测试函数。
- `tests/test_sow_monthly.py`：15 个测试函数。
- `tests/test_sow_official.py`：17 个测试函数。
- `tests/test_sow_discovery.py`：13 个测试函数。

当前四组猪周期离线测试合计 71 个测试函数；参数化测试在 pytest 中可能展开为更多测试 case。

## 3. 已完成的重要工作

### V1 稳定性与本地体验

- 修复 `trading_date` 与 `observation_date` 的日期语义：
  - `trading_date` 只表示真实日线交易日。
  - `observation_date` 表示实时估算的观测/运行日。
  - 周末强制运行时，观测日不会覆盖真实交易日。
  - 邮件运行摘要只显示可靠的交易日。
- Windows PowerShell 脚本使用进程级 UTF-8，避免中文和 emoji 日志触发 GBK `UnicodeEncodeError`。
- 公共 SearXNG 实例自动发现在示例配置中默认关闭。

### V2 官方数据基础

根据最近提交记录：

| 提交 | 内容 |
| --- | --- |
| `ad8cdee` | 新增 MOA 周度猪周期数据 |
| `f7ffead` | 新增能繁母猪月度产能数据模型 |
| `d6bc672` | 新增单一官方 URL 保守读取器 |
| `6dae641` | 新增受控官方文章发现器 |
| `2522a0f` | MOA 周报拆分安全历史回填与日常增量 |
| `0361804` | 新增猪周期 SQLite schema |
| `6309f6d` | 持久化 MOA 周度记录 |
| `19d0a8a` | 持久化能繁母猪月度记录 |
| `801c773` | 新增本地 known-state 读取 |
| `3690541` | 新增有状态 MOA 周度增量协调器 |
| `0cf912e` | 新增 V2 Data Snapshot v0 |
| `a79efaf` | 新增猪周期 revision schema v0 |
| `03c65dd` | 原子持久化猪周期 revisions |
| `e31c2a0` | 新增 revision baseline 审计与 bootstrap |
| `0fa83d8` | 新增 System-Knowledge as-of reader |
| `6b88df0` | 校验 revision future business time |
| `4fe56f3` | 新增 System Historical Trend Wrapper |

真实官网 smoke test 已覆盖 MOA 周报、MOA 母猪数据和 NBS 季度母猪数据的关键文本语义。

## 4. 当前阶段

当前位于 **V2.0 数据基础设施向分析方法论过渡阶段**。

已经具备：

- 官方原始文本和文件的解码/解析。
- 严格的数据日期与发布日期语义。
- 官方域名白名单和全国口径过滤。
- 有硬上限的单 URL、受控发现、历史回填和日常增量请求模式。
- 对真实 HTML 文本节点空白、NBSP、UTF-8、NBS 全国上下文和季度末日期的兼容。
- 独立 SQLite schema，以及 MOA 周度和能繁母猪月度记录的原子持久化。
- `processed_sources`、known-state 读取和有状态 MOA 周度日常增量闭环。
- V2 Data Snapshot v0，可纯本地展示数据库概况和当前有效数据。
- 已建立正式长期数据库 `data/pig_cycle.sqlite3`，并成功写入、展示首条真实 MOA 周度数据。
- 已建立正式 Trend Feature Layer：`Fact Layer → Trend Feature Layer → future Cycle Layer`。当前可计算最新/前值、相邻及累计变化、末端连续方向、真实观测间隔和 irregular 标记，但不输出周期阶段、置信度或投资判断。
- 当前历史深度已完成一次工程审计：MOA 为 12 条连续周度观测（2026-05-21 至 2026-08-06，全部相邻 7 天），NBS 为 8 个季度末锚点（2024-09 至 2026-06，全部相邻 3 个月）。这些数据足以验证存储和机械趋势链路，但不足以直接宣布周期规律或投资结论。
- 已实现独立 append-only revision schema、normal revision persistence、canonical fingerprint v1、只读 baseline preflight audit 和单事务 baseline bootstrap。current tables 仍是日常 Snapshot/Trend 的有效状态来源；revision tables 尚未接管 current reader。
- 正式 `data/pig_cycle.sqlite3` 的 Formal Revision Baseline Migration 已完成人工验收：12 条 MOA weekly 与 8 条 NBS sow current rows 均已有合法 `baseline_import` replay seed，第二次幂等 audit 完整通过，Production Gate 已开启。
- 已实现 System-Knowledge as-of reader，可仅从 revision tables 按历史 cutoff 重建当时系统已知的 effective state，并保持 current path 与 historical path 隔离。
- 已实现 Future Business-Time Integrity：revision reader 防御既有坏证据，normal save 在数据库 mutation 前拒绝未来业务日期/期间。
- 已实现 System Historical Trend Wrapper，将单个 historical cutoff 下的 System-Knowledge records 交给既有 Trend pure functions，直接返回 `NumericTrendFeatures`。
- 已完成 Historical Calibration Preparation（A2–A3）：具备不可变校准领域模型、System-Knowledge Calibration Input、Forward Outcome、Calibration Finalizer、自然月末 cutoff、完整单行编排和月度 Dataset 编排。

尚未完成：

- 周度价格与月度产能的统一时间序列和数据质量状态。
- Official-Availability as-of reader；System-Knowledge as-of reader 已完成。
- 猪周期阶段模型、V2A 评分或投资信号。
- 与 V1 主 CLI、Web、报告、邮件或 daily pipeline 的集成。

Step 1C、正式 revision baseline migration、System-Knowledge as-of reader、Future Business-Time Integrity、V2 Step 2B-5C-2 System Historical Trend Wrapper，以及 A2–A3 Historical Calibration Preparation 已经完成。下一阶段为 **A4 Calibration Analysis — pending**，具体统计方法尚未冻结；Strict Official-Availability reader、正式 calibration analysis、lead-lag、阈值研究、backtest 和 Cycle Layer 均继续暂停。

### Step 1C 为什么出现

Step 1C 不只是“增加一个本地数据库”，而是 Step 1B 安全理念的直接延续。

Step 1B 已解决“如何安全、克制地获取官方数据”，但如果程序不长期保存已经访问过的 URL、已经拥有的数据日期和成功解析的记录，下一次运行仍可能忘记以前做过什么，从而重复发现、重复请求官方页面。

可以简化为：

- **Step 1B：学会克制地获取数据。**
- **Step 1C：学会记住已经获取过什么。**

Step 1C 计划包含：

- 本地持久化 `MoaWeeklyRecord`。
- 本地持久化 `SowMonthlyRecord`。
- 按 `source_url + collection_date/month` 等稳定键去重。
- 自动恢复 `known_urls` 和 `known_dates`。
- 已有数据尽量使用纯离线查询。
- 检测缺失周次和缺失月份。
- 保存来源 URL、发布日期等可追溯信息。
- 使用原子写入；数据损坏时明确报错，不静默覆盖或丢弃。
- 由统一协调层管理 bootstrap/history 与 incremental 更新。

`known_urls` / `known_dates` 不只是调用便利参数，而是网络安全机制：它们让程序在发起请求前就知道“这个 URL 已访问过”“这个日期的数据已拥有”，从而跳过不必要的官方网络请求。因此，Step 1C 是“有状态、有记忆的安全数据获取”，不是与 Step 1B 无关的独立存储功能。

### Current effective storage、Revision history 与 Baseline

**Current effective storage：** `moa_weekly_records` 以 `collection_date` 为业务唯一键，`sow_monthly_records` 以 `(month, source_type)` 为业务唯一键，只保存当前 effective payload，并继续服务 current Snapshot、current Trend 和日常流程。`processed_sources` 负责成功处理 URL 的永久记忆、请求前去重和来源映射，不是 revision history。

当前 Trend 的 `as_of` 只对调用方传入的 current records 按 `publish_date` 过滤。它能阻止 `publish_date > cutoff` 的当前可见记录进入计算，但不能恢复被覆盖的旧版本、重建历史时点的 effective state，或判断系统当时是否已经抓到该版本。因此，当前 `as_of` 不是完整 point-in-time database。

**Revision history 已实现：** `moa_weekly_record_revisions` 与 `sow_monthly_record_revisions` 独立保存 append-only revision evidence。normal ingest 中，`processed_sources`、current decision 和 revision evidence 在同一事务中原子提交；`ingest_origin=normal_ingest`，`inserted/updated` 的 `sets_current=1`，`unchanged/older_ignored/conflict/order_unknown` 的 `sets_current=0`。同一 `(source_url, payload_fingerprint)` 通过 UNIQUE identity 幂等，重复 revision 不刷新 `observed_at`、`save_status`、`sets_current` 或 origin。

Canonical fingerprint v1 已冻结：MOA 使用 `schema=moa_weekly.v1` 及 `collection_date`、`publish_date`、`period_label`、仔猪/生猪/玉米/豆粕/育肥猪饲料价格；明确排除本地派生的 `derived_pig_corn_ratio`、`source_url` 和 revision metadata。Sow 使用 `schema=sow_monthly.v1` 及 `month`、`source_type`、`sow_inventory`、`mom_change`、`yoy_change`、`publish_date`。两者均使用 canonical JSON → UTF-8 → SHA-256 lowercase hex；数值必须 finite、拒绝 bool、将 `-0.0` 规范成 `+0.0`，并使用 `float.hex()`；golden digest tests 已冻结该契约。revision row 仍保存完整 payload，因此 MOA 的同 fingerprint 不代表 `derived_pig_corn_ratio` 必然相同，baseline existing-revision audit 必须继续逐字段比较完整 payload。

revision 表示一个具体官方 payload/version；save status 表示该版本首次被系统观察时相对于当时 current state 的处理结果。v0 不建设通用 event-sourcing。未来 system-knowledge 查询需要依据 revision append order、`observed_at`、稳定 revision id 和保存判定，按历史观察顺序确定当时状态，而不能只筛选时间后随意取最新版。

Point-in-time 必须区分三类时间：

- business time：Weekly 的 `collection_date`、Sow 的 `month`；
- official time：官方 `publish_date`，表示理论公开时间；
- system knowledge time：`observed_at`，表示系统首次成功获取并解析该版本的时间。

Point-in-time contract 必须区分 official-availability as-of 与 system-knowledge as-of；后者已经实现，前者仍暂停。历史页面可能早已发布但直到多年后才由系统回填，两种语义不能混用；不得用 `publish_date` 冒充 `observed_at`，也不得用迁移时间冒充 `publish_date`。

`older_ignored`、`conflict`、`order_unknown` 和来自新 URL 的 `unchanged` 版本现在均可保留完整 revision，但不得因此静默改变 current effective row。conflict 不得在未来历史查询中任意选择；发布日期缺失时也不得使用本地处理时间猜测官方先后。

当前还有一个明确 detection boundary：Coordinator 会永久跳过已成功处理的 URL，所以官方若原地修改同一 URL，系统不会自动发现。调用方若直接再次调用 `save_*`，同 URL、同业务键但不同 payload/fingerprint 仍会进入状态机并可能 append 新 revision；这不是自动 revalidation。未来可评估人工或低频、受控的 revalidation，但不得以高频轮询、无限重试或大规模重复抓取解决。

**Baseline contract：** baseline revision 使用 `ingest_origin=baseline_import`、`save_status=NULL`、`sets_current=1`，表示 revision 能力启用前仍保留在 current table 的 effective payload 被作为未来 replay 的已知起始 seed，并不声称这是该版本历史上第一次出现。`observed_at` 优先使用可信的 `current.updated_at`：它表示当前 exact effective payload 最后一次真正 INSERT/UPDATE 进入 current table 的系统 UTC 时间；`unchanged`、`older_ignored`、`conflict` 和 `order_unknown` 均不刷新它。只有 `updated_at` 可解析、timezone-aware、UTC offset 为 0 且不晚于本次 `imported_at` 时才可采用，否则使用 `imported_at` 并记录 `import_time_fallback`。不得使用 `created_at`、`publish_date`、`processed_at` 或其它 URL 时间猜测 exact-payload system knowledge。

`processed_sources` 在 baseline preflight 中只作为 source mapping / provenance consistency evidence：检查 `record_kind`、`source_url`、`business_key`、`source_type`、`publish_date` 和 `processed_at`。URL 映射到不同业务键、Sow 来源类型冲突或 Weekly `source_type` 非 NULL 属于 blocker；processed row 缺失、发布日期不一致、时间异常或 `processed_at > current.updated_at` 属于 warning/audit evidence。`processed_at` 只证明 URL 首次成功登记；same URL later changed payload 时它会早于 current payload，因此不能单独决定 baseline `observed_at`。

`PigCycleStorage.audit_revision_baseline()` 使用 read-only SQLite URI，不自动初始化 schema；数据库缺失时抛 `FileNotFoundError`，revision schema 缺失时保留 `sqlite3.OperationalError`，且不写数据库。`PigCycleStorage.bootstrap_revision_baseline()` 不自动初始化 schema，使用 `BEGIN IMMEDIATE`，在事务中以单个 `imported_at` 重建 fresh plan；blocker 存在时 zero writes，否则 append 全部缺失 baseline revisions，保持 current 和 `processed_sources` 不变，并在同一事务执行 post-write audit。只有 `complete=true` 才提交，任意 SQL 或 post-audit 失败均 rollback。

结果语义严格区分：`ready_to_apply` 表示 preflight 无 blocker，且每个 current row 都有合法 existing coverage 或明确可插入方案；`complete` 表示数据库当前实际已满足每个 current row 的合法 revision replay seed coverage；`applied` 表示本次 bootstrap 实际成功提交了至少一条 baseline revision。典型首次 preflight 为 `true/false/false`，成功 bootstrap 为 `true/true/true`，再次 audit 为 `true/true/false`。

`BASELINE COMPLETE` 不能通过 revision row count 与 current row count 相等来判断。必须逐 current business key 验证同 `source_url`、同 production fingerprint、完整 stored payload 逐字段一致、`sets_current=1`；existing normal revision 仅在 `save_status` 为 `inserted/updated` 且 `sets_current=1` 时可作为 seed。按 `observed_at ASC, revision_id ASC` replay 后，最终 sets-current revision 必须与 current table 一致，且不存在 blocker；baseline 不得修改 current 或 `processed_sources`。当前无法恢复 revision 能力启用前未保存的被覆盖或忽略 payload，这一历史缺口继续保留。

**Formal Baseline Migration 已完成，Production Gate 已开启：** 迁移前正式库 census 为 MOA current 12、Sow current 8、`processed_sources` 20（MOA/Sow 各 12/8）；MOA 范围为 2026-05-21 至 2026-08-06，Sow 为 8 条 NBS、范围 2024-09 至 2026-06。迁移前 revision tables 不存在。

迁移前使用 `sqlite3.Connection.backup()` 创建并保留 verified backup：`data/backups/pig_cycle-before-revision-baseline-20260814T200002.369029Z.sqlite3`。backup 的 integrity、logical counts 和三张 existing tables digests 均与 source 一致。显式 `initialize_schema()` 后，两张 revision tables 已创建且初始为 0/0；current/processed counts 与 migration safety digests 均未变化：MOA `511414fbe728220298db64054c07caf394ffba95bddf6a61d0d4b0f8220ea318`，Sow `e6fc08442b53622e826b1c61eb541a5944431d8ec9726e16a10a742863c29ba3`，processed `a593ec8a8b39067b6fa546e400617c4787d2e8ad5ff50d29c9009d26f252ed9d`。这些是 migration safety evidence，不是 domain fingerprint v1。

正式 read-only preflight 显示 Weekly/Sow current 与 insertable 分别为 12/12 和 8/8，existing 均为 0；20 条记录全部使用可信 `current.updated_at`，无 `import_time_fallback`、warning 或 blocker，结果为 `ready_to_apply=true, complete=false, applied=false`。单事务 bootstrap 随后成功插入 12+8 条 baseline revisions，同事务 post-write audit 通过，结果为 `true/true/true`。第二次幂等 audit 显示 insertable 0、existing 12+8、`true/true/false`，无 warning/blocker。

最终验证 `integrity_check=ok`，current/processed counts 和上述 digests 保持不变；MOA/Sow revision counts 为 12/8，全部为 `ingest_origin=baseline_import`、`save_status=NULL`、`sets_current=1`，`stop_reasons=[]`。这意味着既有 current state 已有合法 revision replay seed，future normal revision-aware save 不再受旧 current 缺少 baseline 的迁移阻断；该迁移本身不表示 System-Knowledge Reader、Official-Availability Reader、历史校准、回测或 Cycle Layer 已完成。System-Knowledge Reader 是随后由 `0fa83d8` 独立完成的能力。

当前历史链路已经形成：`revision tables → System-Knowledge Reader → domain records → Historical Trend Wrapper → existing Trend pure functions → NumericTrendFeatures`。Storage 负责截止 cutoff 哪个版本可见；Trend 继续只做机械计算，不查询 SQLite、不理解 `processed_sources`，也不处理 revision conflict。System-Knowledge as-of 已完成，Official-Availability as-of 仍暂停。current Snapshot、current Trend 和正常 current state 仍读取 `moa_weekly_records` / `sow_monthly_records`；historical System-Knowledge path 只读取 revision tables。`processed_sources` 仍只负责 URL memory/provenance mapping。historical wrapper 已完成，但不表示正式 historical calibration、lead-lag、阈值研究或 backtest 已开始，Cycle Layer 继续暂停。

### System-Knowledge As-Of 与 Future Business-Time Integrity

`PigCycleStorage.get_moa_weekly_records_as_of_system(cutoff)` 和 `PigCycleStorage.get_sow_monthly_records_as_of_system(cutoff)` 已正式实现。`cutoff` 必须是 timezone-aware `datetime`，可使用任意 aware timezone，进入 reader 后统一规范为 UTC；可见性边界为 inclusive 的 `observed_at <= cutoff`。System-Knowledge visibility 只由 Knowledge Time 决定，不使用 `publish_date`。

Historical replay 的 MOA business key 为 `collection_date`，Sow business key 为 `(month, source_type)`。revision 按 `observed_at ASC, revision_id ASC` 重放；只有 `sets_current=1` 能改变 effective historical state。`sets_current=0` 的 `unchanged`、`older_ignored`、`conflict` 和 Sow `order_unknown` 只保留历史 evidence，不能创建、覆盖或删除 effective state。当前没有 tombstone/delete 语义。

System reader 只从 revision tables 恢复领域记录，不 fallback current tables，也不允许 current-state leakage。MOA replay 恢复 revision 中保存的完整 payload，包括原样保存的 `derived_pig_corn_ratio`，不在 historical reader 中重新派生。

Baseline import revision 不是“历史第一版本”，而是 revision 能力启用时 current effective payload 的 replay seed。seed 只有到达自己的 `observed_at` 才可见；cutoff 早于 baseline seeds 时返回空历史是正确行为。不得把 baseline backdate 到 `publish_date`，不得因业务期间较早向过去回填，也不得假设系统在 seed 的 Knowledge Time 之前已经知道 exact payload。

Reader 使用 fail-loud defensive replay。stored `observed_at` 必须是可按 ISO 解析、timezone-aware 且 UTC offset 为 0 的字符串；metadata 与 business time 也必须一致。损坏证据抛出带 `table`、`revision_id`、`field` 的 `PigCycleRevisionDataError`，不静默跳过。完整性校验发生在 cutoff visibility 判断之前，因此即使坏 revision 的 `observed_at` 晚于本次 cutoff，也不能被隐藏。

三种时间保持严格分离：

- **Business Time：** MOA `collection_date`；Sow `month`，表示 completed period。
- **Knowledge Time：** revision `observed_at`，决定 System-Knowledge visibility。
- **Publish Time：** 官方 `publish_date`；本阶段不参与 System-Knowledge visibility 或 future-business integrity，也不建立 `publish_date <= cutoff/observed_at` 规则。

China Business Time 固定为 UTC+08:00，使用 Python 标准库 fixed offset，不随 caller cutoff 的 timezone 改变。MOA 要求 `collection_date <= observed_at` 转为 UTC+08:00 后的 local date，允许同日。Sow 的 `month` 对 `nbs`、`moa_reported`、`moa_estimate` 均表示 completed period，按该月最后一个日历日解释，并要求 `month_end <= observed local date`；实现正确处理大小月、闰年和年份边界。

同一规则也用于 normal ingest。`save_moa_weekly()` 和 `save_sow_monthly()` 各只调用一次 `_utc_now()`，同一 observation instant 同时用于 business-time validation、current timestamps、`processed_at` 和 revision `observed_at`；校验在数据库 mutation 前完成。stored revision corruption 使用 `PigCycleRevisionDataError`，尚未写入的 normal input contradiction 使用 `ValueError`。

Current 与 historical 路径保持独立：

- Current path：`current tables → domain records → Trend pure functions`。
- Historical System-Knowledge path：`revision tables → System-Knowledge Reader → domain records → Historical Trend Wrapper → Trend pure functions`。

`calculate_moa_weekly_trend_as_of_system(...)` 直接执行 Reader → Trend；`calculate_sow_inventory_trend_as_of_system(...)` 在 Reader 后先按指定 `source_type` 隔离，再交给 Trend。wrapper 不重复 revision replay、business-time validation 或排序，也不重新派生 revision 中保存的 `derived_pig_corn_ratio`。System-Knowledge visibility 仍然只有 inclusive `observed_at <= cutoff`；wrapper 不增加 `publish_date <= cutoff`，也不把 cutoff 传给 Trend 的旧 publish-date `as_of`。

Trend 仍是纯函数层，不理解 SQLite、`observed_at`、`revision_id`、`sets_current`、baseline 或 cutoff。Strict Official-Availability Reader、publish-date historical replay、official availability intersection、A4 Calibration Analysis、lead-lag、threshold research、backtest、Cycle Stage、historical Snapshot 和 investment signal fusion 均继续暂停。

### Historical Calibration Preparation（A2–A3）

当前正式能力链为：

```text
Revision
→ System-Knowledge Reader
→ Historical Trend
→ Calibration Input
→ Forward Outcome
→ Calibration Finalizer
→ Monthly Cutoff Generator
→ Full Calibration Row Builder
→ Calibration Dataset Builder
```

A2–A3 已完成 `Calibration Domain Models`、`Calibration Input Builder`、`Forward Outcome Builder`、`Calibration Row Finalizer`、`Monthly Cutoff Generator`、`Full Calibration Row Builder` 和 `Calibration Dataset Builder`。实际 dataset 执行关系是：

```text
Calibration Dataset Builder
→ Monthly Cutoff Generator
→ for each cutoff:
    Full Calibration Row Builder
    → Calibration Input Builder
    → if start provenance exists:
        Forward Outcome Builder(s)
      else:
        outcomes = ()
    → Calibration Finalizer
→ tuple[CalibrationRow, ...]
```

Calibration INPUT 严格只使用 historical cutoff 当时按 `observed_at <= cutoff` 可见的 System-Knowledge evidence；OUTCOME 可以使用 cutoff 之后、截至调用方显式给出的 `evaluation_cutoff` 可见的 evidence，但两者物理隔离，未来 evidence 不得反向进入 INPUT。revision baseline 只是 revision 能力启用时 current effective payload 的 replay seed，只能从自身 `observed_at` 起可见，不能 backdate 或倒装成更早的系统知识，因此严格 `system_observed` calibration 的现有历史长度天然有限，这不是数据错误。

合法质量状态 `COMPLETE`、`INPUT_INCOMPLETE`、`OUTCOME_INCOMPLETE` 和 `INCOMPLETE` 均保留；Dataset Builder 不做 quality filtering。无 start provenance 属于 INPUT incomplete，不是 `ForwardOutcome.MISSING`；如果 INPUT 因 Sow 或 Trend 缺失而 incomplete，但 start provenance 存在，仍构建 future outcomes。`AVAILABLE + NOT_MATURED`、`AVAILABLE + MISSING` 等 mixed outcomes 都是合法记录。真正异常必须原样传播，不得静默跳过 horizon、month 或返回 partial dataset。

Calibration Experiment v0.1 使用 UTC+08:00 自然日历月末 `23:59:59.999999` 作为机械 sampling cutoff。这是可调整的 research assumption，不是猪周期领域硬规则。`SowSourceType`、`horizon_weeks`、`evaluation_cutoff` 和 `max_offset_days` 均由调用方显式提供，当前没有默认或硬编码的 4/12/24 周 horizon。

当前 Dataset 仅为 `tuple[CalibrationRow, ...]`，尚无 DataFrame、CSV、新数据库表或 dataset persistence。A4 Calibration Analysis 仍为 pending，尚未开始 Feature Extraction、calibration statistics、win rate、mean return、correlation、lead-lag calibration、threshold、Cycle Stage、Backtest 或股票/ETF outcome analysis，也尚未冻结 A4 的具体方法。

### V2 阶段关系与最终目标

当前与后续阶段关系如下：

```text
Step 1A：核心猪周期指标与基础数据模型
  ↓
Step 1B：安全、低频、官方优先的数据获取层
  ↓
Step 1C：有状态的本地数据仓库与增量更新协调
  ↓
统一猪周期时间序列与数据质量检查
  ↓
核心指标与周期阶段模型
  ↓
与 V1 股票 / ETF 市场数据汇合
  ↓
V2 投资观察、风险提示与初步投资辅助建议
```

V2 的最终目标不是单纯建立猪价或养殖行业数据库。项目仍然是个人猪周期投资观察系统，当前数据基础设施只是为后续投资分析建立可靠地基。

长期数据链路是：

```text
官方猪周期产业数据
（能繁母猪、生猪、仔猪、玉米、豆粕、饲料、猪粮比等）
  ↓
统一时间序列与数据质量检查
  ↓
猪周期核心指标
  ↓
周期阶段判断
  ↓
与 V1 股票 / ETF 市场数据结合
  ↓
牧原股份、温氏股份、新希望、神农集团、养殖 ETF 等标的观察
  ↓
形成阶段性投资观察、风险提示和初步投资辅助建议
```

Step 1C 暂不实现周期评分或投资建议，是因为当前阶段需要先保证数据可靠、可追溯、可复用。这不表示 V2 已转变为纯行业数据库项目。后续仍需让产业数据与 V1 股票/ETF 分析系统汇合，但未来规划不得描述为当前已完成能力。

### 长期分析原则

V2 不是单纯的数据采集器、数据库或猪价仪表盘。其长期目标保持稳定：从官方产业事实出发，形成趋势分析和猪周期状态判断，进一步连接公司盈利能力、市场预期与股价定价，最终回到投资机会观察、风险提示和初步辅助建议，并重新连接 V1 的股票 / ETF 分析能力。

具体分析方法必须允许迭代。阶段划分、时间窗口、指标权重和阈值都属于需要通过历史数据校准的候选方法；当前六阶段框架不是不可修改的金融定律。架构应保证模型被合并、拆分、重定义或概率化时，不需要重建底层采集、来源追溯和 SQLite 存储体系。

分析遵循多指标、多时间尺度原则：单个时点或单个指标不能直接形成周期或投资判断，更重要的是一段时间内的方向、持续性、速度和拐点。周度和月度指标应尊重各自天然频率，不为统一时间轴制造虚假精度；不同指标之间的矛盾不应被强行抹平，因为矛盾本身可能包含领先、滞后或结构变化的信息。

当前 Trend Layer 已正式落地的特征包括：`observation_count`、latest/previous、latest change/pct、window start、cumulative change/pct、末端连续上涨/下降变化次数、`latest_streak_direction`、observation keys、真实 interval units、interval unit 和 irregular interval flag。streak count 表示从序列末端向前连续同方向的**相邻变化次数**，不是记录条数、周数或月数。

Snapshot 与 Trend 的方向语义必须保持区分：Snapshot 的“所示记录方向”描述整个展示窗口内全部相邻变化的符号形态；Trend 的 terminal streak 只描述序列末端向前的连续相邻变化。因此，同一序列可以同时表现为 Snapshot 的“混合”和 Trend 的末端连续下降，两者不冲突，不能直接用 terminal streak 替换 Snapshot 的 whole-window direction helper。

产业周期、公司盈利和市场定价必须分层：行业改善不等于所有猪企同样受益；公司层还需考虑销售价格、完全成本、出栏量、养殖效率和业务结构。行业玉米、豆粕和饲料价格可以描述行业盈利环境，必要时可作为低置信度代理，但不能冒充公司的真实完全成本。股票价格还可能领先产业基本面，因此最终必须判断市场已提前交易了多少。

重要的长期方向和关键模型决策必须同步写入仓库 Markdown，而不能只存在于聊天记录。分析框架发生实质变化时，应更新对应专题文档，并保留改变内容及原因。当前可迭代方法见 `docs/ANALYSIS_FRAMEWORK.md`，关键决策及其理由见 `docs/DECISIONS.md`。

## 5. 关键设计决定

### 数据语义

- 数据所属日期、发布日期和运行/观测日期必须分离。
- MOA 周报的 `collection_date` 严格来自正文采集日，不使用发布日或运行日猜测。
- 母猪 `month` 表示数据所属月，不是网页发布月。
- 核心字段缺失时明确报错，不填 `0`。

### 官方数据来源

数据获取优先级为：

1. 官方直接提供的 CSV / Excel / PDF 等数据文件。
2. 有正式入口、正式文档且适合使用的官方公开 API。
3. 已知且明确的官方 HTML / 数据 URL。
4. 只有在数据缺失且确有必要时，才进行有限、受控的官方页面发现。

项目不是单纯追求 API 优先，而是优先选择官方、公开、稳定、可追溯、请求成本最低的数据入口。不要进行隐藏 API 探测、全站扫描、限制绕过或高频请求。

### Step 1B 的策略调整与受控自动化

V2 早期获取农业农村部等政府官方网站数据时，曾尝试较广泛地读取官方列表页和历史页面，有时需要翻较多页面才能寻找历史数据。出于安全、稳定和对官方服务器友好的考虑，项目随后主动收紧数据获取策略。

当前核心原则是：

> **可靠性、可追溯性、低请求量 > 自动发现能力。**

项目应避免：

- 全站扫描和大量自动翻页。
- 高频或并发抓取。
- 无限重试、因自动重试导致请求量快速放大，或任何限制绕过行为。
- 每次运行重新扫描历史页面。
- 对已经获取过的数据重复请求。

项目也不完全拒绝自动发现。若所有 URL 都必须人工输入，系统会失去必要的自动化价值。因此 Step 1B 最终选择“受控自动化”：

- 已知数据直接使用。
- 已经获取过的数据不重复获取。
- 只有数据缺失时才进行有限发现。
- 历史回填可以使用稍多请求，但必须有不可突破的硬上限。
- 日常增量保持极低请求量。
- 发生拒绝访问、验证码、登录、反爬或请求预算达到上限时立即停止并明确报错，不持续重试。

这一理念已经体现在当前代码中：

- `sow_official.py`
  - 使用官方域名白名单。
  - 针对调用者给定的单一官方 URL 读取 HTML / CSV / Excel / PDF。
  - 不承担全站发现职责。
- `sow_discovery.py`
  - 只读取一个调用者提供的列表入口。
  - 单次最多 5 次请求、最多检查 2 篇候选。
  - 不自动翻页、不并发、不无限重试。
- `moa_weekly.py`
  - 明确区分 bootstrap/history 与 incremental。
  - 历史回填有列表页、文章数和总 GET 数硬上限。
  - 日常增量最多 2 次 GET，且支持通过 `known_urls` / `known_dates` 跳过已知数据。

- 调用者必须给定明确的官方 URL 或列表入口。
- 所有候选 URL 在请求前再次验证官方域名。
- 403、429、验证码、登录要求、明显反爬或重定向应立即停止。
- 不自动重试、不并发、不更换 IP、不绕验证码。
- 请求数由代码内的硬预算统一约束，不依赖调用者自律。

### 全国口径与来源类型

- `SowSourceType` 明确区分 `nbs`、`moa_reported` 和 `moa_estimate`。
- 解析器不猜测来源类型，由调用者或经过校验的官方域名决定。
- NBS 的“全国生猪存栏……其中，能繁母猪存栏……”可继承紧邻的全国上下文。
- 省、市、县等地方母猪数据不作为正式全国记录。
- 当前只采集官方报告或 NBS 数值，不在获取层自行构造 `moa_estimate`。

### 政策区间

2026 年能繁母猪正常保有量为 3750 万头左右。政策区间集中定义在模块常量中，不散落在业务逻辑：

- `< 88%`：`red_low`
- `88% ≤ ratio < 92%`：`yellow_low`
- `92% ≤ ratio ≤ 103%`：`green`
- `103% < ratio ≤ 106%`：`yellow_high`
- `> 106%`：`red_high`

这是官方产能调控区间，不是 V2A 猪周期评分，也不直接代表去产能、底部、上行早期或股票买点。

### 安全与配置

- 真实密钥、邮箱授权码和个人配置只能保存在本地 `.env`，不得提交。
- `.env.example` 只保留安全占位符。
- GitHub Actions 密钥只能使用 GitHub Secrets。
- 默认稳定性优先，不把 V2 实验性数据层提前接入 V1 主流程。

## 6. 开发与验证约定

- 建议运行环境：Python 3.11 独立虚拟环境。
- 不需要网络的测试应使用 mocked session / fixture，不访问真实官网。
- 真实官网验证应保持手动、低频、单入口和可控请求数。
- 修改 Python 后优先运行相关离线 pytest、`py_compile` 和 `git diff --check`。
- 未经明确确认不执行 `git commit`、`git tag` 或 `git push`。

## 7. 历史上下文锚点

最近一次重要上下文刷新基线（2026-08-12）：

- `0cf912e feat: add pig cycle data snapshot`

该 commit 仅用于标记本文档最近一次系统性核对项目状态时的历史上下文，不代表未来的当前 HEAD。实时分支、提交和工作区状态必须以实际执行的 `git status`、`git log` 等命令为准。

### Trend Layer 真实数据验证锚点（2026-08-14）

`04fd9e3 feat: add pig cycle trend features` 已通过 256 项测试和正式 SQLite 数据 smoke test。以下数值仅记录该时点的真实验证结果，不代表未来数据库中的永久业务值：

- MOA 仔猪（6 条）：latest `22.42`，latest change 约 `-0.58`（`-2.52%`），cumulative change 约 `+0.78`（`+3.60%`），terminal down count `2`。
- MOA 生猪：latest `11.13`，latest change 约 `-0.09`（`-0.80%`），cumulative change 约 `+0.65`（`+6.20%`），terminal down count `3`。
- MOA 派生猪粮比：latest 约 `4.506`，latest change 约 `-0.0364`，cumulative change pct 约 `+6.63%`，terminal down count `3`。
- MOA 实际间隔为 `7/7/7/7/7` 天，irregular 为 `false`。
- NBS 母猪 `3961 → 3904 → 3780`：latest change `-124`（约 `-3.18%`），cumulative change `-181`（约 `-4.57%`），terminal down count `2`；间隔为 `3/3` 个月，irregular 为 `false`。

这些结果全部是机械趋势特征，不是猪周期阶段、趋势确认、置信度或投资判断。

### System-Knowledge 与 Business-Time 里程碑验证（2026-08-15）

- `0fa83d8 feat: add system knowledge as-of reader`：commit 前 Storage `212 passed`，V2 selected regression `411 passed`。
- `6b88df0 feat: validate revision business time`：commit 前 Storage `236 passed`，V2 selected regression `435 passed`。

这些数字只记录对应里程碑当时的本地验收结果，不是永久 API contract；运行中仅出现既有且无关的 FastAPI/Starlette warning。

### System Historical Trend Wrapper 里程碑验证（2026-08-15）

`4fe56f3 feat: add system historical trend wrapper` 完成了单 cutoff 的 System-Knowledge Reader → Trend 薄接线。本阶段本地验收为 historical trend tests `12 passed, 1 warning`、Storage `236 passed, 1 warning`、selected V2 regression `447 passed, 1 warning`。这些数字只记录该里程碑当时的验收结果，不是永久 API contract。
