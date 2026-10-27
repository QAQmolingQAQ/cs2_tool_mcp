# Hammer 批次只读重连观察（2026-10-27）

入口scripts/hammer_batch_status_probe.py --config <private config> --batch <UUID> --report <private report>，核心batch_observation.py。读取持久日志与当前属性，绝不调用编辑、选择、Save、Undo或重放，也不覆盖原日志。

## 状态分离

- 后续批量探针在首次日志中记录producer PID及Windows进程创建时间。检查器用process_identity区分running、exited、pid_reused；访问失败为unknown，旧记录缺字段为not_recorded，均不伪装已退出。
- 逐项日志分开报告已验证修改数、未开始项、未知派发项。日志终态不等于当前内存仍为该状态；preparing等非终态仅在同一生产进程身份确实存活时标in_progress，否则stopped_or_unobserved_unknown。
- 当前属性单独返回是否匹配batch.before以及recorded after。即使值等于请求值，也不能证明操作归属、队列已耗尽或未来不会执行。
- replay_allowed、recovery_authorized、attribution_verified、safe_to_write恒false。该观察不把未知操作升级成可重放或可Undo。

只接受UUID和状态目录下2MiB内记录，核对id、行索引和状态枚举；读取前后日志文件身份必须相同，否则让调用者重新观察而非重发。项目source/profile/config哈希必须与记录上下文匹配才读当前内存；工程不匹配时返回不可用，不探测实体。当前读取沿已有固定哈希/RTTI/完整GUID与属性容器校验。进程状态在内存读取前采样，整个观察非原子，明确返回atomic_snapshot=false。

## 验证

188测试（187通过/1符号链接权限跳过），覆盖进程存活/退出/PID复用/访问失败、未知派发始终禁止重试、错误终态保留未知项及工程失配不读内存。

真实只读观察批次77c90295fbf042c9b2723fc6be596607：journal controlled_test_stop、verified_modified_count1、第二项not_started；当前内存匹配before=true，匹配recorded after=false，说明该批次之后已恢复。producer_state=not_recorded属旧schema事实，不能据此判断旧进程现状。报告C:\CS2_Temp\batch_readonly_status_verified.json。此次未进行任何地图修改，不重跑已经恢复的批次；代码新增的producer字段尚未以新实机修改批次验证，后续自然批次验证，不为计数制造额外编辑。

当前文档仍是隔离UUID bc1d…，最近已验证源6614/原图f489，dirty候选25/saved5；此只读观察不提升clean或完整回滚证明。公开工具105不变。

## 后续

这实现只读重连分类，不是未知派发的安全自动恢复。真正断线/进程崩溃后的操作归属、主线程队列消耗/取消和原生事务边界仍待实机证据；不知道时保留unknown、拒绝重发。下一步将生产者绑定和持久状态查询纳入受限执行入口，继续验证失败/断线场景，然后推进用户要求的玩家上下文、CS2Fixes/cvar、声音与依赖冻结。完整目标保持未完成。
