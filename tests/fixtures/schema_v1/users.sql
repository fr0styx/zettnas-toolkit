-- users.db at schema v1, with seed rows (ARCH-7 upgrade tests). Generated from the v1 init code.
CREATE TABLE api_tokens (
                token_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                masked_token TEXT NOT NULL,
                scopes_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                last_used_at REAL,
                last_used_ip TEXT DEFAULT ''
            );
CREATE TABLE roles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                scopes_json TEXT NOT NULL,
                is_system INTEGER DEFAULT 1,
                created_at REAL NOT NULL
            );
INSERT INTO "roles" VALUES('superadmin','SuperAdmin','Unrestricted access to all subsystems, hardware, security, and user management','["*"]',1,1.79280783115904974e+09);
INSERT INTO "roles" VALUES('storage_admin','StorageAdmin','Manage disks, pools, SMART tests, scrubs, shares, and filesystem quotas','["storage:*", "shares:*", "system:view", "hardware:read", "logs:read", "audit:read"]',1,1.79280783115904974e+09);
INSERT INTO "roles" VALUES('app_operator','AppOperator','Deploy, inspect, restart, and edit Docker containers and apps','["containers:*", "system:view", "logs:read"]',1,1.79280783115904974e+09);
INSERT INTO "roles" VALUES('backup_operator','BackupOperator','Trigger, view, and schedule configuration and data backups','["backup:*", "storage:read", "shares:read", "system:view", "logs:read"]',1,1.79280783115904974e+09);
INSERT INTO "roles" VALUES('share_user','ShareUser','Access permitted file shares, personal home directory, and media ingest','["shares:read", "shares:user_write", "system:view"]',1,1.79280783115904974e+09);
INSERT INTO "roles" VALUES('auditor','Auditor','Read-only access to system telemetry, metrics, event logs, and status','["*:read", "system:view"]',1,1.79280783115904974e+09);
CREATE TABLE security_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                actor_id TEXT,
                actor_username TEXT,
                actor_ip TEXT,
                actor_user_agent TEXT,
                status TEXT NOT NULL,
                details_json TEXT DEFAULT '{}',
                timestamp REAL NOT NULL
            );
INSERT INTO "security_audit_log" VALUES(1,'auth.migration.completed','admin-00000000-0000-0000-0000-000000000001','admin','127.0.0.1','system','success','{"migrated_from": ["security.json", "sessions.json", "api_tokens.json"]}',1.79280783116154479e+09);
CREATE TABLE sessions (
                session_id_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                last_active_at REAL NOT NULL,
                ip_address TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                is_remembered INTEGER DEFAULT 0
            );
CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                display_name TEXT NOT NULL,
                email TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                role_id TEXT NOT NULL REFERENCES roles(id),
                status TEXT DEFAULT 'active',
                must_change_password INTEGER DEFAULT 0,
                avatar_url TEXT DEFAULT '',
                home_directory TEXT DEFAULT '',
                storage_quota_bytes INTEGER DEFAULT 0,
                preferences_json TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_login_at REAL,
                last_login_ip TEXT DEFAULT ''
            , mfa_enabled INTEGER DEFAULT 0, mfa_secret TEXT DEFAULT '', mfa_recovery_codes_json TEXT DEFAULT '[]', idp_type TEXT DEFAULT 'local', idp_sub TEXT DEFAULT '');
INSERT INTO "users" VALUES('admin-00000000-0000-0000-0000-000000000001','admin','Administrator','','$argon2id$v=19$m=1024,t=1,p=1$9IAnZet89V4$qoRJSGiegMpL11felQIOsg','superadmin','active',1,'','/mnt/user/homes/admin',0,'{}',1.79280783116154479e+09,1.79280783116154479e+09,NULL,'',0,'','[]','local','');
INSERT INTO "users" VALUES('25048f8e-db6e-4438-b904-89da986af62a','fixtureuser','Fixture User','','$argon2id$v=19$m=1024,t=1,p=1$HOIjPW1A9KU$xwsgfGF1yEIoPp3aGOKXuQ','share_user','active',0,'','/mnt/user/homes/fixtureuser',0,'{}',1.7928078311676402e+09,1.7928078311676402e+09,NULL,'',0,'','[]','local','');
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX idx_api_tokens_token_hash ON api_tokens(token_hash);
CREATE INDEX idx_api_tokens_user_id ON api_tokens(user_id);
CREATE INDEX idx_security_audit_ts ON security_audit_log(timestamp DESC);
