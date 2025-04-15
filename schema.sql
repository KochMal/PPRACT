CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    role TEXT CHECK(role IN ('client', 'admin')) DEFAULT 'client',
    registered BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    report_text TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    admin_feedback TEXT,
    FOREIGN KEY(user_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    master_id INTEGER,
    address TEXT NOT NULL,
    status TEXT CHECK(status IN ('pending', 'in_progress', 'completed')) DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(client_id) REFERENCES users(telegram_id),
    FOREIGN KEY(master_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS masters (
    user_id INTEGER PRIMARY KEY,
    busyness INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS master_requests (
    user_id INTEGER PRIMARY KEY,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(telegram_id)
);

CREATE TRIGGER IF NOT EXISTS update_busyness_on_assign
AFTER UPDATE ON requests
FOR EACH ROW
WHEN NEW.status = 'in_progress' AND OLD.status != 'in_progress' AND NEW.master_id IS NOT NULL
BEGIN
    UPDATE masters SET busyness = busyness + 1 WHERE user_id = NEW.master_id;
END;

CREATE TRIGGER IF NOT EXISTS update_busyness_on_complete
AFTER UPDATE ON requests
FOR EACH ROW
WHEN NEW.status = 'completed' AND OLD.status != 'completed' AND NEW.master_id IS NOT NULL
BEGIN
    UPDATE masters SET busyness = busyness - 1 WHERE user_id = NEW.master_id;
END;

CREATE TRIGGER IF NOT EXISTS update_busyness_on_master_change
AFTER UPDATE OF master_id ON requests
FOR EACH ROW
WHEN NEW.status = 'in_progress' AND NEW.master_id != OLD.master_id AND NEW.master_id IS NOT NULL
BEGIN
    UPDATE masters SET busyness = busyness - 1 WHERE user_id = OLD.master_id AND OLD.master_id IS NOT NULL;
    UPDATE masters SET busyness = busyness + 1 WHERE user_id = NEW.master_id;
END;

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_requests_client_id ON requests(client_id);
CREATE INDEX IF NOT EXISTS idx_requests_master_id ON requests(master_id);