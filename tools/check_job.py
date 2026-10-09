from collections.abc import Generator
from typing import Any
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.fal_common import FalQueue, MODELS, FalError, output_messages

class CheckJobTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            model = str(tool_parameters.get('model') or '').strip()
            if model not in MODELS.values():
                raise FalError('Choose the model used for this request.')
            client = FalQueue(self.runtime.credentials)
            task = client.task(model, tool_parameters.get('request_id'))
            state = client.status(task)
            status = str(state.get('status') or 'UNKNOWN').upper()
            if status == 'COMPLETED':
                yield from output_messages(self, model, task, client.result(task),
                                           include_file=tool_parameters.get('return_file', True) is not False)
            elif status in ('IN_PROGRESS', 'IN_QUEUE'):
                yield self.create_json_message({'request_id': task['request_id'], 'model': model,
                                                'status': status,
                                                'queue_position': state.get('queue_position'),
                                                'logs': state.get('logs') or []})
                yield self.create_text_message(f'Fal status is {status}; job not finished, request_id={task["request_id"]}')
                yield self.create_variable_message('request_id', task['request_id'])
                yield self.create_variable_message('status', status)
            else:
                raise FalError(f'Fal task state {status}; request_id={task["request_id"]}; details={str(state)[:400]}')
        except Exception as exc:
            raise ValueError(f'Fal check-job failed: {exc}') from exc
