# logged_agent.py
import json
import time
from browser_use import Agent
from browser_use.llm.messages import BaseMessage
from browser_use.agent.views import AgentOutput

class LoggedAgent(Agent):
    def __init__(self, *args, log_path="training_data.jsonl", task_index=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_path = log_path
        self.task_index = task_index
        self._pending_logs = []
        self._step_counter = 0
        self._step_start_time = None

    def _log_training_data(self, input_messages: list[BaseMessage], parsed: AgentOutput):
        try:
            self._step_counter += 1
            
            # 스텝 소요 시간 계산
            step_time = None
            if self._step_start_time:
                step_time = round(time.time() - self._step_start_time, 2)
            self._step_start_time = time.time()
            
            data = {
                "task_index": self.task_index,
                "step_number": self._step_counter,
                "step_time_seconds": step_time,
                "input": [m.model_dump() for m in input_messages],
                "output": parsed.model_dump(),
                "is_meaningful": None  # 수동 입력용: True/False/None
            }
            self._pending_logs.append(data)
        except Exception as e:
            self.logger.warning(f"Failed to buffer training data: {e}")

    def flush_logs(self, success: bool):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                for data in self._pending_logs:
                    data["success"] = success
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
            
            # 검증
            self.logger.info(f"✅ {len(self._pending_logs)}개 스텝 저장 완료")
        except Exception as e:
            self.logger.warning(f"Failed to flush logs: {e}")
        finally:
            self._pending_logs = []
            self._step_counter = 0
            self._step_start_time = None

    async def get_model_output(self, input_messages):
        parsed = await super().get_model_output(input_messages)
        self._log_training_data(input_messages, parsed)
        return parsed