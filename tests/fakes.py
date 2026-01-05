class FakeLiveExecutor:
    def __init__(self):
        self.cancel_all_calls = []

    def cancel_all(self, token_id: str):
        self.cancel_all_calls.append(token_id)
