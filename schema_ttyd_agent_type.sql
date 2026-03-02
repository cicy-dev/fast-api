-- Update ttyd_config table to add agent_type field
ALTER TABLE ttyd_config ADD COLUMN agent_type VARCHAR(50) DEFAULT NULL;

-- Create index for agent_type for faster queries
CREATE INDEX idx_agent_type ON ttyd_config(agent_type);