"""Integration tests for Sprint 1 feature flag behavior."""

import pytest
from unittest.mock import MagicMock, patch

from src.memory.sprint1_manager import Sprint1MemoryManager


class TestSprint1FeatureFlag:
    """Tests for Sprint 1 feature flag behavior."""

    @patch('src.memory.sprint1_manager.load_settings')
    def test_disabled_by_default(self, mock_load_settings):
        """Test that Sprint 1 is disabled by default."""
        mock_load_settings.return_value = {
            "memory": {
                "sprint1": {
                    "enabled": False,
                }
            },
            "database": {
                "mongo_uri": "mongodb://localhost:27017",
                "db_name": "test_db",
            }
        }
        
        manager = Sprint1MemoryManager()
        
        assert manager.enabled is False

    @patch('src.memory.sprint1_manager.load_settings')
    def test_enabled_when_configured(self, mock_load_settings):
        """Test that Sprint 1 can be enabled via config."""
        mock_load_settings.return_value = {
            "memory": {
                "sprint1": {
                    "enabled": True,
                    "redact_secrets": True,
                    "checkpoint_every_step": True,
                    "max_checkpoint_observation_chars": 2000,
                    "max_recent_turns_in_context": 12,
                }
            },
            "database": {
                "mongo_uri": "mongodb://localhost:27017",
                "db_name": "test_db",
            }
        }
        
        # Mock MongoDB client to avoid connection
        with patch('src.memory.sprint1_manager.MongoClient') as mock_client:
            manager = Sprint1MemoryManager(mock_client)
            
            # Note: In real scenario, initialization might fail without real DB
            # This test verifies the config is read correctly
            assert manager.sprint1_config.get("enabled") is True

    @patch('src.memory.sprint1_manager.load_settings')
    def test_fallback_to_defaults(self, mock_load_settings):
        """Test that missing config values use defaults."""
        mock_load_settings.return_value = {
            "memory": {
                "sprint1": {
                    "enabled": True,
                }
            },
            "database": {
                "mongo_uri": "mongodb://localhost:27017",
                "db_name": "test_db",
            }
        }
        
        with patch('src.memory.sprint1_manager.MongoClient'):
            manager = Sprint1MemoryManager()
            
            # Should have default values
            assert manager.sprint1_config.get("redact_secrets") is True
            assert manager.sprint1_config.get("checkpoint_every_step") is True
            assert manager.sprint1_config.get("max_checkpoint_observation_chars") == 2000
            assert manager.sprint1_config.get("max_recent_turns_in_context") == 12

    @patch('src.memory.sprint1_manager.load_settings')
    def test_no_mongo_uri_disables_feature(self, mock_load_settings):
        """Test that missing MongoDB URI disables the feature."""
        mock_load_settings.return_value = {
            "memory": {
                "sprint1": {
                    "enabled": True,
                }
            },
            "database": {}  # No mongo_uri
        }
        
        manager = Sprint1MemoryManager()
        
        # Should be disabled due to missing URI
        assert manager.enabled is False

    @patch('src.memory.sprint1_manager.load_settings')
    def test_graceful_degradation_on_error(self, mock_load_settings):
        """Test that errors during initialization disable the feature gracefully."""
        mock_load_settings.return_value = {
            "memory": {
                "sprint1": {
                    "enabled": True,
                }
            },
            "database": {
                "mongo_uri": "mongodb://localhost:27017",
                "db_name": "test_db",
            }
        }
        
        # Simulate initialization failure
        with patch('src.memory.sprint1_manager.TaskStore') as mock_store:
            mock_store.side_effect = Exception("Connection failed")
            
            manager = Sprint1MemoryManager()
            
            # Should be disabled after error
            assert manager.enabled is False


class TestSprint1NoOpWhenDisabled:
    """Tests that Sprint 1 operations are no-ops when disabled."""

    @patch('src.memory.sprint1_manager.load_settings')
    def test_ensure_task_exists_returns_none(self, mock_load_settings):
        """Test that ensure_task_exists returns None when disabled."""
        mock_load_settings.return_value = {
            "memory": {"sprint1": {"enabled": False}},
            "database": {}
        }
        
        manager = Sprint1MemoryManager()
        
        result = manager.ensure_task_exists("session-1", "Goal")
        
        assert result is None

    @patch('src.memory.sprint1_manager.load_settings')
    def test_save_checkpoint_returns_false(self, mock_load_settings):
        """Test that save_checkpoint returns False when disabled."""
        mock_load_settings.return_value = {
            "memory": {"sprint1": {"enabled": False}},
            "database": {}
        }
        
        manager = Sprint1MemoryManager()
        
        result = manager.save_checkpoint(last_action="test")
        
        assert result is False

    @patch('src.memory.sprint1_manager.load_settings')
    def test_compile_context_returns_none(self, mock_load_settings):
        """Test that compile_context returns None when disabled."""
        mock_load_settings.return_value = {
            "memory": {"sprint1": {"enabled": False}},
            "database": {}
        }
        
        manager = Sprint1MemoryManager()
        
        result = manager.compile_context(recent_turns=[])
        
        assert result is None

    @patch('src.memory.sprint1_manager.load_settings')
    def test_update_task_status_returns_false(self, mock_load_settings):
        """Test that update_task_status returns False when disabled."""
        mock_load_settings.return_value = {
            "memory": {"sprint1": {"enabled": False}},
            "database": {}
        }
        
        manager = Sprint1MemoryManager()
        
        result = manager.update_task_status("completed")
        
        assert result is False
