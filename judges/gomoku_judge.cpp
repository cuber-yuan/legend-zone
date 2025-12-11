#include<cstdio>
#include<cstdlib>
#include<cstring>
#include<iostream>
#include<string>
#include<list>
#include<ctime>
#include"jsoncpp/json.h" // 假设您有这个 JSON 库
using namespace std;

// 棋盘大小，五子棋通常是 15x15
const int SIZE = 15;
// 定义四个方向的步进 (横、竖、两对角线)
const int dx[4] = {1, 0, 1, 1};
const int dy[4] = {0, 1, 1, -1};

// 棋盘状态：0: 空, 1: 玩家1 (黑), 2: 玩家2 (白)
int Grid[SIZE][SIZE];

// 初始化棋盘
void init_grid() {
    for (int i = 0; i < SIZE; i++) {
        for (int j = 0; j < SIZE; j++) {
            Grid[i][j] = 0;
        }
    }
}

// 检查坐标是否在棋盘内
bool inGrid(int x, int y) {
    return x >= 0 && x < SIZE && y >= 0 && y < SIZE;
}

// 检查棋盘是否已满 (平局条件)
bool gridFull() {
    for (int i = 0; i < SIZE; i++) {
        for (int j = 0; j < SIZE; j++) {
            if (Grid[i][j] == 0) {
                return false;
            }
        }
    }
    return true;
}

/**
 * 放置棋子
 * @param color 棋子颜色 (1 或 2)
 * @param x x 坐标 (0 到 SIZE-1)
 * @param y y 坐标 (0 到 SIZE-1)
 * @return true 放置成功，false 坐标无效或已被占用
 */
bool placeAt(int color, int x, int y) {
    // 原始 JavaScript 裁判代码使用的是 0 到 SIZE-1 的坐标
    if (inGrid(x, y) && Grid[x][y] == 0) {
        Grid[x][y] = color;
        return true;
    }
    return false;
}

/**
 * 检查在 (x, y) 放置 color 棋子后是否获胜 (五子连珠)
 * @param color 棋子颜色
 * @param x, y 放置的坐标
 * @return true 获胜, false 尚未获胜
 */
bool checkWin(int color, int x, int y) {
    for (int k = 0; k < 4; k++) {
        int count = 1; // 已经包含当前放置的棋子
        
        // 检查一个方向
        for (int i = 1; i < 5; i++) {
            int nx = x + dx[k] * i;
            int ny = y + dy[k] * i;
            if (inGrid(nx, ny) && Grid[nx][ny] == color) {
                count++;
            } else {
                break;
            }
        }

        // 检查相反方向
        for (int i = 1; i < 5; i++) {
            int nx = x - dx[k] * i;
            int ny = y - dy[k] * i;
            if (inGrid(nx, ny) && Grid[nx][ny] == color) {
                count++;
            } else {
                break;
            }
        }
        
        if (count >= 5) {
            return true; // 发现五子连珠
        }
    }
    return false;
}

// 玩家 ID (0 或 1) 到颜色 (1 或 2) 的映射
int playerIDToColor(int player_id) {
    return player_id + 1; // 0 -> 1 (黑), 1 -> 2 (白)
}

int main() {
    // 确保与 snake_judge 的输入处理方式一致
    string str;
    string temps;
    getline(cin, temps);
    str += temps;

    Json::Reader reader;
    Json::Value input, output;

    // 假设输入 JSON 遵循 snake_judge 的结构，包含 'log' 字段
    if (!reader.parse(str, input)) {
        // 解析失败，输出错误
        cerr << "JSON Parse Error" << endl;
        return 1;
    }

    // 初始化棋盘
    init_grid();

    Json::Value log = input["log"];

    // 初始请求 (log 为空)
    if (log.size() == 0) {
        output["command"] = "request";
        // 初始请求不需要内容，但为了兼容性可以发送一个空对象
        output["content"] = Json::Value(Json::objectValue); 
    } else {
        // 遍历所有回合的输入
        for (Json::Value::UInt i = 1; i < log.size(); i += 2) {
            // Gomoku 玩家ID： 0: Black, 1: White
            int player_id = (i - 1) / 2 % 2; 
            int color = playerIDToColor(player_id); // 1: Black, 2: White
            int other_player_id = 1 - player_id;
            
            // 响应应该在 i 处 (奇数索引)
            Json::Value response = log[i][player_id]["response"];

            if (response.isNull() || !response.isObject() || 
                !response["x"].isInt() || !response["y"].isInt()) {
                // 无效输入/格式错误
                output["command"] = "finish";
                output["display"]["winner"] = playerIDToColor(other_player_id);
                output["display"]["error"] = "INVALID INPUT FORMAT";
                break;
            }

            int x = response["x"].asInt();
            int y = response["y"].asInt();

            if (!placeAt(color, x, y)) {
                // 放置失败 (无效坐标或已被占用)
                output["command"] = "finish";
                output["display"]["winner"] = playerIDToColor(other_player_id);
                output["display"]["error"] = "INVALID MOVE";
                break;
            }

            // 检查获胜
            if (checkWin(color, x, y)) {
                output["command"] = "finish";
                output["display"]["winner"] = color;
                break;
            } 
            
            // 检查平局
            if (gridFull()) {
                output["command"] = "finish";
                output["display"]["winner"] = -1; // -1 表示平局
                break;
            }

            // 如果是最后一回合，准备请求下一个玩家的行动
            if (i == log.size() - 1) {
                output["command"] = "request";
                // 发送上一个玩家的动作给下一个玩家
                output["content"][other_player_id]["x"] = x;
                output["content"][other_player_id]["y"] = y;
            }
        }
    }

    Json::FastWriter writer;
    cout << writer.write(output) << endl;

    return 0;
}