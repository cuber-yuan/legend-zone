import json

BOARD_SIZE = 3

# Same interface as GomokuJudge so the game loops and bot I/O protocol match.
# Player 1 = X (black), Player 2 = O (white). board[y][x]: 0 empty, 1 X, 2 O.
class TicTacToeJudge:
    def __init__(self):
        self.board = [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_player = 1
        self.move_history = []
        self.black_player_type = 'human'
        self.white_player_type = 'bot'
        self.black_executor = None
        self.white_executor = None
        self.winner = 0
        self.game_id = None
        self.is_terminated = False

    def terminate(self):
        self.is_terminated = True

    def new_game(self, black_player_type, white_player_type, black_executor, white_executor):
        self.board = [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_player = 1
        self.move_history = []
        self.winner = 0
        self.black_player_type = black_player_type
        self.white_player_type = white_player_type
        self.black_executor = black_executor
        self.white_executor = white_executor

    def is_valid_move(self, x, y):
        return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE and self.board[y][x] == 0

    def apply_move(self, x, y):
        if not self.is_valid_move(x, y):
            return False
        self.board[y][x] = self.current_player
        self.move_history.append({'x': x, 'y': y, 'player': self.current_player})
        self.current_player = 3 - self.current_player
        return True

    def check_win(self, x, y):
        player = self.board[y][x]
        if all(self.board[y][i] == player for i in range(BOARD_SIZE)):
            return player
        if all(self.board[i][x] == player for i in range(BOARD_SIZE)):
            return player
        if x == y and all(self.board[i][i] == player for i in range(BOARD_SIZE)):
            return player
        if x + y == BOARD_SIZE - 1 and all(self.board[i][BOARD_SIZE - 1 - i] == player for i in range(BOARD_SIZE)):
            return player
        return 0

    def is_board_full(self):
        return all(self.board[y][x] != 0 for y in range(BOARD_SIZE) for x in range(BOARD_SIZE))

    def to_json(self):
        return json.dumps({
            "board": self.board,
            "current_player": self.current_player,
            "move_history": self.move_history
        })

    def send_action_to_ai(self):
        data = {
            "move_history": self.move_history,
            "your_side": self.current_player,  # 1 for X, 2 for O
        }
        return json.dumps(data)
