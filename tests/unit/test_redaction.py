"""Unit tests for secret redaction."""

import pytest

from src.memory.redaction import redact_text, redact_dict, redact_list, redact_value


class TestRedactText:
    """Tests for text redaction."""

    def test_redact_openai_key(self):
        """Test redacting OpenAI-style API keys."""
        text = "My API key is sk-1234567890abcdefghijklmnop"
        result = redact_text(text)
        
        assert "[REDACTED_API_KEY]" in result
        assert "sk-1234567890abcdefghijklmnop" not in result

    def test_redact_aws_key(self):
        """Test redacting AWS access keys."""
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        result = redact_text(text)
        
        assert "[REDACTED_AWS_KEY]" in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_redact_github_token(self):
        """Test redacting GitHub tokens."""
        text = "token = ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_text(text)
        
        assert "[REDACTED_GITHUB_TOKEN]" in result

    def test_redact_bearer_token(self):
        """Test redacting Bearer tokens."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        result = redact_text(text)
        
        assert "Bearer [REDACTED_TOKEN]" in result

    def test_redact_mongodb_connection_string(self):
        """Test redacting MongoDB connection strings with passwords."""
        text = "mongodb://user:secretpassword123@cluster.mongodb.net/db"
        result = redact_text(text)
        
        assert "[REDACTED_PASSWORD]" in result
        assert "secretpassword123" not in result

    def test_redact_private_key_header(self):
        """Test redacting private key headers."""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA..."
        result = redact_text(text)
        
        assert "[REDACTED_PRIVATE_KEY_HEADER]" in result

    def test_preserve_normal_text(self):
        """Test that normal text is preserved."""
        text = "This is a normal sentence with no secrets."
        result = redact_text(text)
        
        assert result == text

    def test_preserve_file_paths(self):
        """Test that file paths are preserved."""
        text = "The file is located at /home/user/project/src/main.py"
        result = redact_text(text)
        
        assert result == text

    def test_empty_string(self):
        """Test handling empty strings."""
        assert redact_text("") == ""
        assert redact_text(None) is None


class TestRedactDict:
    """Tests for dictionary redaction."""

    def test_redact_nested_dict(self):
        """Test redacting nested dictionaries."""
        data = {
            "api_key": "sk-1234567890abcdefghijklmnop",
            "config": {
                "password": "secret123",
                "host": "localhost",
            },
        }
        result = redact_dict(data)
        
        assert "[REDACTED_API_KEY]" in str(result)
        assert "[REDACTED_PASSWORD]" in str(result)
        assert "localhost" in str(result)  # Preserved

    def test_redact_list_in_dict(self):
        """Test redacting lists within dictionaries."""
        data = {
            "tokens": ["ghp_abcdefghijklmnopqrstuvwxyz1234567890", "normal-value"],
        }
        result = redact_dict(data)
        
        assert "[REDACTED_GITHUB_TOKEN]" in str(result)
        assert "normal-value" in str(result["tokens"])


class TestRedactList:
    """Tests for list redaction."""

    def test_redact_list_of_secrets(self):
        """Test redacting a list of secrets."""
        items = [
            "sk-1234567890abcdefghijklmnop",
            "normal-text",
            "AKIAIOSFODNN7EXAMPLE",
        ]
        result = redact_list(items)
        
        assert "[REDACTED_API_KEY]" in result[0]
        assert result[1] == "normal-text"
        assert "[REDACTED_AWS_KEY]" in result[2]


class TestRedactValue:
    """Tests for generic value redaction."""

    def test_redact_string(self):
        """Test redacting a string value."""
        result = redact_value("sk-1234567890abcdefghijklmnop")
        assert "[REDACTED_API_KEY]" in result

    def test_redact_dict(self):
        """Test redacting a dict value."""
        result = redact_value({"key": "sk-1234567890abcdefghijklmnop"})
        assert "[REDACTED_API_KEY]" in str(result)

    def test_redact_list(self):
        """Test redacting a list value."""
        result = redact_value(["sk-1234567890abcdefghijklmnop"])
        assert "[REDACTED_API_KEY]" in str(result)

    def test_preserve_other_types(self):
        """Test that non-string types are preserved."""
        assert redact_value(123) == 123
        assert redact_value(True) is True
        assert redact_value(None) is None
