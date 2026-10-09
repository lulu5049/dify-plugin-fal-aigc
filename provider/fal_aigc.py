from typing import Any
from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

class FalAigcProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        key = str(credentials.get('api_key') or '').strip()
        # Do not trigger a billable model call while saving credentials.
        if len(key) < 10 or any(c.isspace() for c in key):
            raise ToolProviderCredentialValidationError('Please enter a valid Fal API Key.')
