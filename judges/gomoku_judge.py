import json
# from .. import CodeExecutor # 假设 CodeExecutor 在这里

BOARD_SIZE = 15

## TODO： all judges should implement in same way

class GomokuJudge:
    def __init__(self):
        # Coordinate system explanation:
        # x represents column (horizontal): 0 1 2 3 4 ... 14 (left to right)
        # y represents row (vertical):      0 1 2 3 4 ... 14 (top to bottom)
        # 
        # Board layout:
        #     x  0 1 2 3 4 5 6 7 8 9 ...14
        #   y ┌─────────────────────────────
        #   0 │  . . . . . . . . . . . . . . .
        #   1 │  . . . . . . . . . . . . . . .
        #   2 │  . . . . . . . . . . . . . . .
        #   3 │  . . . ★ . . . . . . . ★ . . .
        #   4 │  . . . . . . . . . . . . . . .
        #   5 │  . . . . . . . . . . . . . . .
        #   6 │  . . . . . . . . . . . . . . .
        #   7 │  . . . . . . . ★ . . . . . . .
        #   8 │  . . . . . . . . . . . . . . .
        #   9 │  . . . . . . . . . . . . . . .
        #  10 │  . . . . . . . . . . . . . . .
        #  11 │  . . . ★ . . . . . . . ★ . . .
        #  12 │  . . . . . . . . . . . . . . .
        #  13 │  . . . . . . . . . . . . . . .
        #  14 │  . . . . . . . . . . . . . . .
        #
        # Access: board[y][x] = board[row][column]
        # Example: board[3][7] is the center star point
        
        self.board = [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_player = 1  # 1: 黑, 2: 白
        self.move_history = []
        
        # 新增：玩家类型和执行器
        self.black_player_type = 'human'
        self.white_player_type = 'bot'
        self.black_executor = None
        self.white_executor = None
        self.winner = 0
        self.game_id = None
        self.is_terminated = False # <-- 新增终止标志

    def terminate(self):
        """Mark the game as terminated to stop its execution loop."""
        self.is_terminated = True
        # 可以在这里清理和此游戏相关的特定资源
        # if self.black_executor:
        #     self.black_executor.cleanup()
        # if self.white_executor:
        #     self.white_executor.cleanup()

    def new_game(self, black_player_type, white_player_type, black_executor, white_executor):
        """Initialize a new game with player configurations."""
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
        self.move_history.append({'x':x, 'y':y, 'player': self.current_player}) # 记录下棋方
        self.current_player = 3 - self.current_player  # 1<->2
        return True

    def check_win(self, x, y):
        player = self.board[y][x]
        directions = [(1,0), (0,1), (1,1), (1,-1)]
        for dx, dy in directions:
            count = 1
            for d in [1, -1]:
                nx, ny = x, y
                while True:
                    nx += dx * d
                    ny += dy * d
                    if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and self.board[ny][nx] == player:
                        count += 1
                    else:
                        break
            if count >= 5:
                return player
        return 0

    def to_json(self):
        return json.dumps({
            "board": self.board,
            "current_player": self.current_player,
            "move_history": self.move_history
        })

    def send_action_to_ai(self):
        # last_move: (player, x, y)
        data = {
            "move_history": self.move_history,
            "your_side": self.current_player, # 1 for Black, 2 for White
        }
        return json.dumps(data)

    def receive_action_from_ai(self):
        # 读取AI的落子
        raw = input()
        move = json.loads(raw)
        x, y = move["x"], move["y"]
        return x, y

        

if __name__ == "__main__":
    judge = GomokuJudge()
    winner = 0
    while True:
        # 发送当前状态给当前玩家AI
        last_move = judge.move_history[-1] if judge.move_history else None
        judge.send_action_to_ai(judge.current_player, last_move)
        # 接收AI的落子
        x, y = judge.receive_action_from_ai()
        if not judge.apply_move(x, y):
            print(json.dumps({"error": "Invalid move"}))
            break
        winner = judge.check_win(x, y)
        if winner:
            print(json.dumps({"winner": winner}))
            break
        if len(judge.move_history) == BOARD_SIZE * BOARD_SIZE:
            print(json.dumps({"winner": 0}))  # 平局
            break