from dataclasses import dataclass


@dataclass(frozen=True)
class ReadCall:
    prompt: str
    secret: bool


class ScriptedTerminal:
    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.read_calls = []
        self.lines = []
        self.clear_calls = 0

    @property
    def output(self):
        return "\n".join(self.lines)

    def read(self, prompt, *, secret=False):
        self.read_calls.append(ReadCall(prompt, secret))
        value = self.inputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def write(self, text, *, style=None):
        del style
        self.lines.append(text)

    def clear(self):
        self.clear_calls += 1


class RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        self.events.append((context, event_type, payload, step, phase))


class FailingSink:
    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        del context, event_type, payload, step, phase
        raise RuntimeError("observer failed")


class NeverCancelled:
    def check(self):
        return None

    def remaining_seconds(self):
        return float("inf")
