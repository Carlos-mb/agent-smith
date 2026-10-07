"""WorkerOutput sends every print to the agent immediately."""

from agent_smith.sandbox import WorkerOutput


class FakeConnection:
    """Stand-in for one end of a multiprocessing Pipe: records what is sent."""

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def test_each_write_is_sent_at_once():
    connection = FakeConnection()
    output = WorkerOutput(connection)

    assert output.write("ab") == 2
    assert output.write("") == 0
    assert output.write("cde") == 3

    assert connection.sent == [
        {"type": "output", "text": "ab"},
        {"type": "output", "text": "cde"},
    ]


def test_print_can_use_worker_output():
    connection = FakeConnection()

    print("hola", file=WorkerOutput(connection), flush=True)

    assert "".join(message["text"] for message in connection.sent) == "hola\n"
