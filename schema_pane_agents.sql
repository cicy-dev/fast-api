-- Create pane_agents table
CREATE TABLE IF NOT EXISTS pane_agents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pane_id VARCHAR(255) NOT NULL,
    agent_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_pane_agent (pane_id, agent_name),
    INDEX idx_pane_id (pane_id),
    INDEX idx_agent_name (agent_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
