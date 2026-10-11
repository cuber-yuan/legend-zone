import json

COLS = 7
ROWS = 6
CONNECT = 4

# board[y][x] with y=0 the TOP row and y=ROWS-1 the bottom, x the column.
# Same indexing convention as GomokuJudge so the shared match services and the
# replay payload work unchanged.
DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


class ConnectFourJudge:
    """Connect Four rules engine.

    Deliberately shaped like GomokuJudge (new_game / apply_move / check_win /
    send_action_to_ai / move_history) so app/connect4.py can reuse the same
    bot services. The one intentional difference: a move is a COLUMN, and
    gravity decides the row. apply_move still accepts a second argument so
    callers written against the Gomoku signature keep working, but ignores it.
    """

    def __init__(self):
        self.board = self._empty_board()
        self.current_player = 1
        self.move_history = []
        self.black_player_type = 'human'
        self.white_player_type = 'bot'
        self.black_executor = None
        self.white_executor = None
        self.winner = 0
        self.game_id = None
        self.is_terminated = False

    @staticmethod
    def _empty_board():
        return [[0 for _ in range(COLS)] for _ in range(ROWS)]

    def terminate(self):
        self.is_terminated = True

    def new_game(self, black_player_type, white_player_type, black_executor, white_executor):
        self.board = self._empty_board()
        self.current_player = 1
        self.move_history = []
        self.winner = 0
        self.is_terminated = False
        self.black_player_type = black_player_type
        self.white_player_type = white_player_type
        self.black_executor = black_executor
        self.white_executor = white_executor

    def landing_row(self, x):
        """Row a disc dropped in column x would come to rest on, or None."""
        if not 0 <= x < COLS:
            return None
        for y in range(ROWS - 1, -1, -1):
            if self.board[y][x] == 0:
                return y
        return None

    def is_valid_move(self, x, y=None):
        return self.landing_row(x) is not None

    def apply_move(self, x, y=None):
        """Drop a disc into column x. The y argument is ignored by design."""
        row = self.landing_row(x)
        if row is None:
            return False
        self.board[row][x] = self.current_player
        self.move_history.append({'x': x, 'y': row, 'player': self.current_player})
        self.current_player = 3 - self.current_player
        return True

    def check_win(self, x, y):
        """Return the player if the disc at (x, y) completes a line of four."""
        if not (0 <= x < COLS and 0 <= y < ROWS):
            return 0
        player = self.board[y][x]
        if player == 0:
            return 0
        for dx, dy in DIRECTIONS:
            run = 1
            for sign in (1, -1):
                nx, ny = x + dx * sign, y + dy * sign
                while 0 <= nx < COLS and 0 <= ny < ROWS and self.board[ny][nx] == player:
                    run += 1
                    nx += dx * sign
                    ny += dy * sign
            if run >= CONNECT:
                return player
        return 0

    def is_board_full(self):
        return all(self.board[y][x] != 0 for y in range(ROWS) for x in range(COLS))

    def to_json(self):
        return json.dumps({
            "board": self.board,
            "current_player": self.current_player,
            "move_history": self.move_history
        })

    def send_action_to_ai(self):
        return json.dumps({
            "move_history": self.move_history,
            "your_side": self.current_player,  # 1 = first player, 2 = second
        })
