# P104/06设计

沿用现有CI PostgreSQL16服务；从已完成迁移的空fqp_test仅复制schema到fqp_observation_test。唯一脚本在显式opt-in且固定127.0.0.1:5432/fqp/fqp_test环境下运行；复制前检查版本和业务空表，专用owner使用公开的fixture密码，role/database创建不覆盖已有对象。Owner用于故障注入，三个NOLOGIN角色用于真实权限测试；只读角色没有写权限。默认超时配置仅限fixture数据库，不能算目标环境准入。CI继续现有覆盖率要求，观测DSN与PGPASSWORD只作用于测试步骤；来源调用仍由固定样本替代。

无生产账号、来源授权、发布和全量消费迁移改动。P104独立审查结果必须来自独立审查者；作者核对不替代该证据。

独立审查必要修正：recent检查只代表查询节流，未验证当前名单就绪；质量按错误→waiting→recently_checked→healthy报告，附本轮未重新核实说明。无新增来源/事实查询或派生。
