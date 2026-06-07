// 串口协议: {CMD}\n 一行一条命令, CMD 为指令名
// 例: {TAB} {LEFT_CLICK} {MOVE_100_200} {CTRL+C} {MC_500_300}
#include "Keyboard.h"
#include "Mouse.h"
#include "MouseTo.h"

#define SERIAL_BAUD_RATE    115200
#define MAX_MODIFIERS        3
#define MAX_CMD_LENGTH       64

#define DEF_SCREEN_WIDTH     2560
#define DEF_SCREEN_HEIGHT    1440
#define DEF_KEY_PRESS        100
#define DEF_KEY_HOLD          50
#define DEF_KEY_RELEASE       10
#define DEF_MOUSE_CLICK       50
#define DEF_MOUSE_PRESS       30
#define DEF_MOUSE_MOVE        50
#define DEF_MOUSE_JUMP        80

// 鼠标侧键 HID 报告 bitmask (第4/5键), 标准 Mouse.h 未定义
#ifndef MOUSE_BACK
#define MOUSE_BACK            0x08
#endif
#ifndef MOUSE_FORWARD
#define MOUSE_FORWARD         0x10
#endif

struct MouseMap {
  const char* name;
  uint8_t action;
  uint8_t button;
};

int screenW = DEF_SCREEN_WIDTH;
int screenH = DEF_SCREEN_HEIGHT;
uint8_t keyPressDelay = DEF_KEY_PRESS;
uint8_t keyHoldDelay = DEF_KEY_HOLD;
uint8_t keyReleaseDelay = DEF_KEY_RELEASE;
uint8_t mouseClickDelay = DEF_MOUSE_CLICK;
uint8_t mousePressDelay = DEF_MOUSE_PRESS;
uint8_t mouseMoveDelay = DEF_MOUSE_MOVE;
uint8_t mouseMaxJump = DEF_MOUSE_JUMP;
bool stopFlag = false;

char cmdBuffer[MAX_CMD_LENGTH];
uint8_t cmdLen = 0;

struct KeyMap {
  const char* name;
  uint8_t code;
  bool isModifier;
};

const KeyMap keyMap[] PROGMEM = {
  {"CTRL", KEY_LEFT_CTRL, true},
  {"SHIFT", KEY_LEFT_SHIFT, true},
  {"ALT", KEY_LEFT_ALT, true},
  {"WIN", KEY_LEFT_GUI, true},
  {"ESC", KEY_ESC, false},
  {"TAB", KEY_TAB, false},
  {"ENTER", KEY_RETURN, false},
  {"SPACE", ' ', false},
  {"BACKSPACE", KEY_BACKSPACE, false},
  {"UP", KEY_UP_ARROW, false},
  {"DOWN", KEY_DOWN_ARROW, false},
  {"LEFT", KEY_LEFT_ARROW, false},
  {"RIGHT", KEY_RIGHT_ARROW, false},
  {"F1", KEY_F1, false},{"F2", KEY_F2, false},{"F3", KEY_F3, false},
  {"F4", KEY_F4, false},{"F5", KEY_F5, false},{"F6", KEY_F6, false},
  {"F7", KEY_F7, false},{"F8", KEY_F8, false},{"F9", KEY_F9, false},
  {"F10", KEY_F10, false},{"F11", KEY_F11, false},{"F12", KEY_F12, false}
};
const uint8_t keyMapSize = sizeof(keyMap) / sizeof(KeyMap);

const MouseMap mouseMap[] PROGMEM = {
  {"LEFT_CLICK", 0, MOUSE_LEFT}, {"LEFT_PRESS", 1, MOUSE_LEFT}, {"LEFT_RELEASE", 2, MOUSE_LEFT},
  {"RIGHT_CLICK", 0, MOUSE_RIGHT}, {"RIGHT_PRESS", 1, MOUSE_RIGHT}, {"RIGHT_RELEASE", 2, MOUSE_RIGHT},
  {"MIDDLE_CLICK", 0, MOUSE_MIDDLE}, {"MIDDLE_PRESS", 1, MOUSE_MIDDLE}, {"MIDDLE_RELEASE", 2, MOUSE_MIDDLE}
};
const uint8_t mouseMapSize = sizeof(mouseMap) / sizeof(MouseMap);

void releaseAll() {
  Keyboard.releaseAll();
  Mouse.release(MOUSE_LEFT);
  Mouse.release(MOUSE_RIGHT);
  Mouse.release(MOUSE_MIDDLE);
}

void resetConfig() {
  screenW = DEF_SCREEN_WIDTH;
  screenH = DEF_SCREEN_HEIGHT;
  keyPressDelay = DEF_KEY_PRESS;
  keyHoldDelay = DEF_KEY_HOLD;
  keyReleaseDelay = DEF_KEY_RELEASE;
  mouseClickDelay = DEF_MOUSE_CLICK;
  mousePressDelay = DEF_MOUSE_PRESS;
  mouseMoveDelay = DEF_MOUSE_MOVE;
  mouseMaxJump = DEF_MOUSE_JUMP;
  MouseTo.setScreenResolution(screenW, screenH);
  MouseTo.setMaxJump(mouseMaxJump);
}

// 修饰键(CTRL/SHIFT/ALT/WIN): 按下不释放, 由 releaseAll() 统一释放
// 普通键: 按下→延迟→释放
void pressKey(uint8_t code, bool isModifier) {
  Keyboard.press(code);
  if (!isModifier) {
    delay(keyPressDelay);
    Keyboard.release(code);
    delay(keyReleaseDelay);
  }
}

// 解析组合键如 "CTRL+SHIFT+TAB": 修饰键先按下, 主键按下后统一释放
void handleKeyCombo(const char* combo) {
  uint8_t modifiers[MAX_MODIFIERS] = {0};
  uint8_t modCount = 0;
  uint8_t mainKey = 0;
  char part[16] = {0};
  uint8_t partLen = 0;

  for (uint8_t i = 0; combo[i] != '\0'; i++) {
    if (combo[i] == '+' || combo[i+1] == '\0') {
      if (combo[i+1] == '\0') part[partLen++] = combo[i];
      part[partLen] = '\0';

      for (uint8_t j = 0; j < keyMapSize; j++) {
        if (strcmp(part, (const char*)pgm_read_word(&keyMap[j].name)) == 0) {
          if (pgm_read_byte(&keyMap[j].isModifier) && modCount < MAX_MODIFIERS) {
            modifiers[modCount++] = pgm_read_byte(&keyMap[j].code);
          } else {
            mainKey = pgm_read_byte(&keyMap[j].code);
          }
          break;
        }
      }
      if (mainKey == 0 && partLen == 1) mainKey = part[0];
      partLen = 0;
      memset(part, 0, sizeof(part));
    } else {
      if (partLen < 15) part[partLen++] = combo[i];
    }
  }

  for (uint8_t i = 0; i < modCount; i++) Keyboard.press(modifiers[i]);
  delay(keyHoldDelay);
  if (mainKey) pressKey(mainKey, false);
  releaseAll();
}

void mouseClick(uint8_t btn) {
  Mouse.press(btn);
  delay(mousePressDelay);
  Mouse.release(btn);
  delay(mouseClickDelay);
}

// 绝对坐标移动: MouseTo 内部追踪光标位置, 分步跳转(mouseMaxJump px/步)
void mouseMoveTo(int x, int y) {
  x = constrain(x, 0, screenW);
  y = constrain(y, 0, screenH);
  MouseTo.setTarget(x, y);
  while (!MouseTo.move() && !stopFlag) delay(2);
  delay(mouseMoveDelay);
}

// 已弃用: 原通过 PROGMEM mouseMap 查表, 改用显式 strcmp 避免指针问题
void handleMouseCommand(const char* cmd) {
  for (uint8_t i = 0; i < mouseMapSize; i++) {
    if (strcmp(cmd, (const char*)pgm_read_word(&mouseMap[i].name)) == 0) {
      uint8_t action = pgm_read_byte(&mouseMap[i].action);
      uint8_t btn = pgm_read_byte(&mouseMap[i].button);
      if (action == 0) mouseClick(btn);
      else if (action == 1) Mouse.press(btn);
      else if (action == 2) Mouse.release(btn);
      return;
    }
  }
}

void handleMouseMove(const char* cmd) {
  if (strcmp(cmd, "MOVE_CENTER") == 0) mouseMoveTo(screenW/2, screenH/2);
  else if (strcmp(cmd, "MOVE_TOP_LEFT") == 0) mouseMoveTo(0,0);
  else if (strncmp(cmd, "MOVE_", 5) == 0) {
    char* underscore = strchr(cmd+5, '_');
    if (underscore != nullptr) {
      int x = atoi(cmd+5);
      int y = atoi(underscore + 1);
      mouseMoveTo(x, y);
    }
  } else if (strncmp(cmd, "MOVE_REL_", 9) == 0) {
    char* underscore = strchr(cmd+9, '_');
    if (underscore != nullptr) {
      int dx = atoi(cmd+9);
      int dy = atoi(underscore + 1);
      Mouse.move(dx, dy);
      delay(mouseMoveDelay);
    }
  }
}

void setup() {
  Keyboard.begin();
  Mouse.begin();
  Serial.begin(SERIAL_BAUD_RATE);
  resetConfig();
  delay(500);
  Serial.println("READY");  // handshake: tell host we are ready for commands
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdLen > 0) {
        cmdBuffer[cmdLen] = '\0';
        if (cmdBuffer[0] == '{' && cmdBuffer[cmdLen-1] == '}') {
          cmdBuffer[cmdLen-1] = '\0';
          char* cmd = cmdBuffer + 1;
          stopFlag = false;
          Serial.print("CMD:");
          Serial.println(cmd);

          // 命令分发: 优先匹配前缀(MC_/MCR_/MOVE) 和全名, 最后回退到 keyMap

          if (strstr(cmd, "+") != nullptr) handleKeyCombo(cmd);
          // MC_x_y: 绝对移动+点击, 省去 mouseMoveDelay/mouseClickDelay, 单次~15ms
          else if (strncmp(cmd, "MC_", 3) == 0) {
            char* underscore = strchr(cmd+3, '_');
            if (underscore != nullptr) {
              int x = atoi(cmd+3);
              int y = atoi(underscore + 1);
              x = constrain(x, 0, screenW);
              y = constrain(y, 0, screenH);
              MouseTo.setTarget(x, y);
              while (!MouseTo.move() && !stopFlag) delay(2);
              Mouse.press(MOUSE_LEFT);
              delay(5);
              Mouse.release(MOUSE_LEFT);
              delay(5);
            }
          }
          // MCR_dx_dy: 相对移动+点击, 用 Mouse.move() 不依赖 MouseTo 内部状态, 大位移自动拆分为 int8 步
          else if (strncmp(cmd, "MCR_", 4) == 0) {
            char* underscore = strchr(cmd+4, '_');
            if (underscore != nullptr) {
              int dx = atoi(cmd+4);
              int dy = atoi(underscore + 1);
              while ((dx != 0 || dy != 0) && !stopFlag) {
                int sx = constrain(dx, -127, 127);
                int sy = constrain(dy, -127, 127);
                Mouse.move(sx, sy);
                dx -= sx;
                dy -= sy;
                delay(2);
              }
              Mouse.press(MOUSE_LEFT);
              delay(5);
              Mouse.release(MOUSE_LEFT);
              delay(5);
            }
          }
          // KEY_DOWN_X / KEY_UP_X: 通用按键按住/释放, 支持单字符(W)和命名键(TAB/ESC/F1等)
          else if (strncmp(cmd, "KEY_DOWN_", 9) == 0) {
            const char* key = cmd + 9;
            if (strlen(key) == 1) Keyboard.press(key[0]);
            else for (uint8_t i = 0; i < keyMapSize; i++)
              if (strcmp(key, (const char*)pgm_read_word(&keyMap[i].name)) == 0)
                { Keyboard.press(pgm_read_byte(&keyMap[i].code)); break; }
          }
          else if (strncmp(cmd, "KEY_UP_", 7) == 0) {
            const char* key = cmd + 7;
            if (strlen(key) == 1) Keyboard.release(key[0]);
            else for (uint8_t i = 0; i < keyMapSize; i++)
              if (strcmp(key, (const char*)pgm_read_word(&keyMap[i].name)) == 0)
                { Keyboard.release(pgm_read_byte(&keyMap[i].code)); break; }
          }
          else if (strstr(cmd, "MOVE") != nullptr) handleMouseMove(cmd);
          else if (strcmp(cmd, "LEFT_CLICK") == 0) mouseClick(MOUSE_LEFT);
          else if (strcmp(cmd, "LEFT_PRESS") == 0) Mouse.press(MOUSE_LEFT);
          else if (strcmp(cmd, "LEFT_RELEASE") == 0) Mouse.release(MOUSE_LEFT);
          else if (strcmp(cmd, "RIGHT_CLICK") == 0) mouseClick(MOUSE_RIGHT);
          else if (strcmp(cmd, "RIGHT_PRESS") == 0) Mouse.press(MOUSE_RIGHT);
          else if (strcmp(cmd, "RIGHT_RELEASE") == 0) Mouse.release(MOUSE_RIGHT);
          else if (strcmp(cmd, "BACK_CLICK") == 0) mouseClick(MOUSE_BACK);
          else if (strcmp(cmd, "BACK_PRESS") == 0) Mouse.press(MOUSE_BACK);
          else if (strcmp(cmd, "BACK_RELEASE") == 0) Mouse.release(MOUSE_BACK);
          else if (strcmp(cmd, "FORWARD_CLICK") == 0) mouseClick(MOUSE_FORWARD);
          else if (strcmp(cmd, "FORWARD_PRESS") == 0) Mouse.press(MOUSE_FORWARD);
          else if (strcmp(cmd, "FORWARD_RELEASE") == 0) Mouse.release(MOUSE_FORWARD);
          else if (strcmp(cmd, "STOP") == 0) { stopFlag = true; releaseAll(); }
          else if (strncmp(cmd, "WAIT_", 5) == 0) delay(atoi(cmd+5));
          else if (strcmp(cmd, "CFG_RESET") == 0) resetConfig();
          // SCR_WxH: 运行时设置屏幕分辨率, MouseTo 绝对移动需要正确的屏幕尺寸
          else if (strncmp(cmd, "SCR_", 4) == 0) {
            char* underscore = strchr(cmd+4, '_');
            if (underscore != nullptr) {
              screenW = atoi(cmd+4);
              screenH = atoi(underscore + 1);
              MouseTo.setScreenResolution(screenW, screenH);
            }
          }
          else {
            // 常用键显式 strcmp 避免 PROGMEM 指针问题; 冷门键(F1~F12/修饰键)才走 keyMap 回退
            if (strcmp(cmd, "TAB") == 0) pressKey(KEY_TAB, false);
            else if (strcmp(cmd, "ESC") == 0) pressKey(KEY_ESC, false);
            else if (strcmp(cmd, "SPACE") == 0) pressKey(' ', false);
            else if (strcmp(cmd, "ENTER") == 0) pressKey(KEY_RETURN, false);
            else if (strcmp(cmd, "BACKSPACE") == 0) pressKey(KEY_BACKSPACE, false);
            else if (strcmp(cmd, "UP") == 0) pressKey(KEY_UP_ARROW, false);
            else if (strcmp(cmd, "DOWN") == 0) pressKey(KEY_DOWN_ARROW, false);
            else if (strcmp(cmd, "LEFT") == 0) pressKey(KEY_LEFT_ARROW, false);
            else if (strcmp(cmd, "RIGHT") == 0) pressKey(KEY_RIGHT_ARROW, false);
            else {
              for (uint8_t i = 0; i < keyMapSize; i++) {
                if (strcmp(cmd, (const char*)pgm_read_word(&keyMap[i].name)) == 0) {
                  pressKey(pgm_read_byte(&keyMap[i].code), pgm_read_byte(&keyMap[i].isModifier));
                  goto endParse;
                }
              }
              if (strlen(cmd) == 1) pressKey(cmd[0], false);
            }
          }
          endParse:
          cmdLen = 0;
          memset(cmdBuffer, 0, sizeof(cmdBuffer));
        } else {
          Serial.print("BAD:");
          Serial.println(cmdBuffer);
          cmdLen = 0;
          memset(cmdBuffer, 0, sizeof(cmdBuffer));
        }
      }
    } else if (cmdLen < MAX_CMD_LENGTH - 1) {
      cmdBuffer[cmdLen++] = c;
    }
  }
}