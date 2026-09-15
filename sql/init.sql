-- ============================================================
--  基于 DeepSeek 的本地聊天机器人 · 数据库初始化脚本
--  用法： mysql -u root -p < sql/init.sql
--  说明： 应用启动时也会自动执行同样的建表逻辑（幂等），
--         并且会自动补一个默认管理员账号 admin / admin123
-- ============================================================

CREATE DATABASE IF NOT EXISTS `deepseek_chat`
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `deepseek_chat`;

-- ------------------------------------------------------------
-- 1. 账号表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
    `id`            INT AUTO_INCREMENT PRIMARY KEY COMMENT '账号ID',
    `username`      VARCHAR(50)  NOT NULL                COMMENT '登录用户名',
    `password_hash` VARCHAR(255) NOT NULL                COMMENT '密码哈希（PBKDF2，绝不存明文）',
    `status`        TINYINT      NOT NULL DEFAULT 1      COMMENT '状态：1=启用 0=禁用',
    `role`          VARCHAR(20)  NOT NULL DEFAULT 'user' COMMENT '角色：admin=管理员 user=普通用户',
    `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_username` (`username`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '账号表';

-- ------------------------------------------------------------
-- 2. 会话表（一个用户可以开多个会话；summary 用于防 token 爆炸）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `conversations` (
    `id`              INT AUTO_INCREMENT PRIMARY KEY COMMENT '会话ID',
    `user_id`         INT          NOT NULL              COMMENT '归属账号',
    `title`           VARCHAR(120) NOT NULL DEFAULT '新对话' COMMENT '会话标题（取首句话生成）',
    `summary`         TEXT         NULL                  COMMENT '被压缩掉的历史摘要（滚动更新）',
    `summary_upto_id` BIGINT       NOT NULL DEFAULT 0    COMMENT '摘要已覆盖到 chat_history 的哪个 id',
    `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY `idx_conv_user` (`user_id`),
    CONSTRAINT `fk_conv_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '会话表';

-- ------------------------------------------------------------
-- 3. 聊天历史表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `chat_history` (
    `id`              BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '消息ID（自增，天然保证时序）',
    `user_id`         INT          NOT NULL              COMMENT '归属账号',
    `conversation_id` INT          NOT NULL              COMMENT '归属会话',
    `role`            VARCHAR(20)  NOT NULL              COMMENT '角色：user / assistant',
    `content`         MEDIUMTEXT   NOT NULL              COMMENT '消息正文',
    `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_hist_conv` (`conversation_id`, `id`),
    KEY `idx_hist_user` (`user_id`),
    CONSTRAINT `fk_hist_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '聊天历史表';

-- ------------------------------------------------------------
-- 4. 默认管理员（密码 admin123，应用启动时会用 PBKDF2 重新哈希写入）
--    这里只做占位，实际以应用启动时的 seed 为准
-- ------------------------------------------------------------
-- INSERT IGNORE INTO `users` (`username`, `password_hash`, `status`, `role`)
-- VALUES ('admin', '<由应用启动时写入>', 1, 'admin');
