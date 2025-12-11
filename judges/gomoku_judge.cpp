#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <ctime>
#include "jsoncpp/json.h"

using namespace std;

// Constant settings from gomoku_judge.txt
const int SIZE = 15; // 
int grid[SIZE][SIZE]; // -1: Empty, 0: Black, 1: White

// Helper to check bounds 
bool inGrid(int x, int y) {
    return x >= 0 && x < SIZE && y >= 0 && y < SIZE;
}

// Helper to check if board is full [cite: 4]
bool gridFull() {
    for (int i = 0; i < SIZE; i++) {
        for (int j = 0; j < SIZE; j++) {
            if (grid[i][j] == -1) return false;
        }
    }
    return true;
}

// Logic to check win condition in specific direction
// Based on JS logic: counts consecutive stones in + and - directions [cite: 8]
int countConsecutive(int color, int x, int y, int dx, int dy) {
    int count = 0;
    // Check forward (including (x,y) at i=0)
    int i;
    for (i = 0; i < 5; i++) { // [cite: 9]
        int nx = x + dx * i;
        int ny = y + dy * i;
        if (!inGrid(nx, ny) || grid[nx][ny] != color) break;
    }
    
    // Check backward (including (x,y) at j=0)
    int j;
    for (j = 0; j < 5; j++) {
        int nx = x - dx * j;
        int ny = y - dy * j;
        if (!inGrid(nx, ny) || grid[nx][ny] != color) break;
    }

    // JS Logic returns i + j - 1 (because the center is counted in both loops) [cite: 13]
    return i + j - 1;
}

// Check all 4 axes for a win [cite: 14]
bool winAfterPlaceAt(int color, int x, int y) {
    if (countConsecutive(color, x, y, 1, 0) >= 5) return true;  // Horizontal
    if (countConsecutive(color, x, y, 0, 1) >= 5) return true;  // Vertical
    if (countConsecutive(color, x, y, 1, 1) >= 5) return true;  // Diagonal
    if (countConsecutive(color, x, y, 1, -1) >= 5) return true; // Anti-Diagonal
    return false;
}

string playerString(int id) {
    return id == 0 ? "0" : "1";
}

int otherPlayerID(int id) {
    return 1 - id;
}

int main() {
    // 1. Read all input (Standard Botzone/Judge method)
    string str;
	string temps;
	getline(cin,temps);
	str+=temps;

    Json::Reader reader;
    Json::Value input, output;
    
    // Parse input JSON
    if (!reader.parse(str, input)) {
        // Handle parse error or empty input safely
        return 0; 
    }

    // Initialize Grid (-1 for empty, matching "undefined" in JS) 
    memset(grid, -1, sizeof(grid));

    Json::FastWriter writer;
    
    // Access the game log
    Json::Value log = input["log"];

    // 2. Initial Request (If log is empty) [cite: 16]
    if (log.size() == 0) {
        output["command"] = "request";
        output["content"]["0"]["x"] = -1; // Dummy values for first move
        output["content"]["0"]["y"] = -1;
        cout << writer.write(output) << endl;
        return 0;
    }

    // 3. Replay the game history
    // Iterate through responses (odd indices in the log) [cite: 17]
    for (int i = 1; i < log.size(); i += 2) {
        bool isLast = (i == log.size() - 1);
        int color = ((i - 1) / 2) % 2; // 0: Black, 1: White [cite: 17]
        string pStr = playerString(color);

        // Extract response
        Json::Value response = log[i][pStr]["response"];
        if (response.isNull()) response = log[i][pStr]["content"]; // Fallback

        // Validate Input Format
        if (!response.isObject() || !response["x"].isInt() || !response["y"].isInt()) {
             // Error: Invalid Input Format [cite: 18]
            output["display"]["winner"] = playerString(otherPlayerID(color));
            output["display"]["error"] = "INVALID INPUT";
            output["command"] = "finish";
            output["content"][playerString(color)] = 0;
            output["content"][playerString(otherPlayerID(color))] = 2;
            cout << writer.write(output) << endl;
            return 0;
        }

        int x = response["x"].asInt();
        int y = response["y"].asInt();

        // Validate Logic (Bounds and Empty Cell) [cite: 6]
        if (inGrid(x, y) && grid[x][y] == -1) {
            // Valid Move: Place stone
            grid[x][y] = color;

            // Check Win/Draw
            if (winAfterPlaceAt(color, x, y)) {
                // Game Over: Win [cite: 21]
                output["command"] = "finish";
                output["display"]["winner"] = playerString(color);
                output["content"][playerString(color)] = 2;
                output["content"][playerString(otherPlayerID(color))] = 0;
                // Add final move to display
                output["display"]["color"] = color;
                output["display"]["x"] = x;
                output["display"]["y"] = y;
                
                // If this happened in history (not current turn), we continue loop? 
                // Usually logic stops here, but for replay, we process until isLast.
                // However, if someone won in history, the log shouldn't continue.
                if (isLast) {
                    cout << writer.write(output) << endl;
                    return 0;
                }
            } 
            else if (gridFull()) {
                // Game Over: Draw [cite: 23]
                output["command"] = "finish";
                output["content"]["0"] = 1;
                output["content"]["1"] = 1;
                output["display"]["err"] = "Draw";
                if (isLast) {
                    cout << writer.write(output) << endl;
                    return 0;
                }
            } 
            else {
                // Game Continues [cite: 24]
                if (isLast) {
                    output["command"] = "request";
                    // Pass the just-placed move to the next player
                    output["content"][playerString(otherPlayerID(color))]["x"] = x;
                    output["content"][playerString(otherPlayerID(color))]["y"] = y;
                    
                    // Display update for real-time viewing [cite: 19]
                    output["display"]["color"] = color;
                    output["display"]["x"] = x;
                    output["display"]["y"] = y;
                    
                    cout << writer.write(output) << endl;
                    return 0;
                }
            }
        } 
        else {
            // Invalid Move (Out of bounds or Occupied) [cite: 26]
            output["display"]["winner"] = playerString(otherPlayerID(color));
            output["display"]["error"] = "INVALID MOVE";
            output["display"]["error_data"] = response;
            output["command"] = "finish";
            output["content"][playerString(color)] = 0;
            output["content"][playerString(otherPlayerID(color))] = 2;
            cout << writer.write(output) << endl;
            return 0;
        }
    }

    return 0;
}