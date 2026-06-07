// 洛克王国减负小助手 v2 — HID-Project 固件
// 库: HID-Project + MouseTo (已修改, 用 BootMouse)
#include "HID-Project.h"
#include "MouseTo.h"

#define SERIAL_BAUD_RATE 115200
#define MAX_CMD_LENGTH 64
#define DEF_SCREEN_WIDTH 2560
#define DEF_SCREEN_HEIGHT 1440
#define DEF_KEY_DELAY 60
#define DEF_MOUSE_DELAY 30
#define DEF_MOUSE_JUMP 80

int screenW = DEF_SCREEN_WIDTH, screenH = DEF_SCREEN_HEIGHT;
uint8_t keyDelay = DEF_KEY_DELAY, mouseDelay = DEF_MOUSE_DELAY, mouseMaxJump = DEF_MOUSE_JUMP;
bool stopFlag = false;
char cmdBuffer[MAX_CMD_LENGTH];
uint8_t cmdLen = 0;

struct KeyEntry { const char* name; uint8_t code; };
const KeyEntry keyMap[] PROGMEM = {
  {"CTRL",KEY_LEFT_CTRL},{"SHIFT",KEY_LEFT_SHIFT},{"ALT",KEY_LEFT_ALT},{"WIN",KEY_LEFT_GUI},
  {"ESC",KEY_ESC},{"TAB",KEY_TAB},{"ENTER",KEY_ENTER},{"SPACE",' '},{"BACKSPACE",KEY_BACKSPACE},
  {"UP",KEY_UP_ARROW},{"DOWN",KEY_DOWN_ARROW},{"LEFT",KEY_LEFT_ARROW},{"RIGHT",KEY_RIGHT_ARROW},
  {"F1",KEY_F1},{"F2",KEY_F2},{"F3",KEY_F3},{"F4",KEY_F4},{"F5",KEY_F5},{"F6",KEY_F6},
  {"F7",KEY_F7},{"F8",KEY_F8},{"F9",KEY_F9},{"F10",KEY_F10},{"F11",KEY_F11},{"F12",KEY_F12},
};
const uint8_t keyMapSize = sizeof(keyMap) / sizeof(KeyEntry);

void releaseAll() { BootKeyboard.releaseAll(); BootMouse.release(MOUSE_LEFT); BootMouse.release(MOUSE_RIGHT); BootMouse.release(MOUSE_MIDDLE); }

uint8_t findKeyCode(const char* name) {
  for (uint8_t i = 0; i < keyMapSize; i++)
    if (strcmp(name, (const char*)pgm_read_word(&keyMap[i].name)) == 0) return pgm_read_byte(&keyMap[i].code);
  return 0;
}

void tapKey(uint8_t code) { BootKeyboard.press(code); delay(keyDelay); BootKeyboard.release(code); delay(keyDelay/2); }

void handleCombo(const char* combo) {
  uint8_t mods[3]={0}, modCount=0, mainKey=0, p=0; char part[16]={0};
  for (uint8_t i=0; combo[i]; i++) {
    if (combo[i]=='+' || combo[i+1]=='\0') {
      if (combo[i+1]=='\0') part[p++]=combo[i]; part[p]='\0';
      uint8_t code=findKeyCode(part);
      if (code) { if (code==KEY_LEFT_CTRL||code==KEY_LEFT_SHIFT||code==KEY_LEFT_ALT||code==KEY_LEFT_GUI) { if (modCount<3) mods[modCount++]=code; } else mainKey=code; }
      else if (p==1) mainKey=part[0];
      p=0; memset(part,0,sizeof(part));
    } else { if (p<15) part[p++]=combo[i]; }
  }
  for (uint8_t i=0; i<modCount; i++) BootKeyboard.press(mods[i]); delay(keyDelay);
  if (mainKey) tapKey(mainKey); releaseAll();
}

void mouseClickAt(int x, int y) {
  x=constrain(x,0,screenW); y=constrain(y,0,screenH); MouseTo.setTarget(x,y);
  while (!MouseTo.move() && !stopFlag) delay(2);
  BootMouse.press(MOUSE_LEFT); delay(5); BootMouse.release(MOUSE_LEFT); delay(5);
}

void mouseClickRel(int dx, int dy) {
  while ((dx!=0||dy!=0) && !stopFlag) { int sx=constrain(dx,-127,127), sy=constrain(dy,-127,127); BootMouse.move(sx,sy); dx-=sx; dy-=sy; delay(2); }
  BootMouse.press(MOUSE_LEFT); delay(5); BootMouse.release(MOUSE_LEFT); delay(5);
}

void setup() {
  BootKeyboard.begin(); BootMouse.begin(); Serial.begin(SERIAL_BAUD_RATE);
  MouseTo.setScreenResolution(screenW, screenH); MouseTo.setMaxJump(mouseMaxJump);
  delay(500); Serial.println("READY v2");
}

void loop() {
  while (Serial.available()) {
    char c=Serial.read();
    if (c=='\n' || c=='\r') {
      if (cmdLen==0) continue;
      cmdBuffer[cmdLen]='\0';
      if (cmdBuffer[0]!='{' || cmdBuffer[cmdLen-1]!='}') { Serial.print("BAD:"); Serial.println(cmdBuffer); cmdLen=0; memset(cmdBuffer,0,sizeof(cmdBuffer)); continue; }
      cmdBuffer[cmdLen-1]='\0'; char* cmd=cmdBuffer+1; stopFlag=false;
      if (strstr(cmd,"+")) handleCombo(cmd);
      else if (strncmp(cmd,"MC_",3)==0) { char* us=strchr(cmd+3,'_'); if (us) mouseClickAt(atoi(cmd+3),atoi(us+1)); }
      else if (strncmp(cmd,"MCR_",4)==0) { char* us=strchr(cmd+4,'_'); if (us) mouseClickRel(atoi(cmd+4),atoi(us+1)); }
      else if (strncmp(cmd,"KEY_DOWN_",9)==0) { uint8_t code=findKeyCode(cmd+9); if (code) BootKeyboard.press(code); else if (strlen(cmd+9)==1) BootKeyboard.press(cmd[9]); }
      else if (strncmp(cmd,"KEY_UP_",7)==0) { uint8_t code=findKeyCode(cmd+7); if (code) BootKeyboard.release(code); else if (strlen(cmd+7)==1) BootKeyboard.release(cmd[7]); }
      else if (strcmp(cmd,"LEFT_CLICK")==0) { BootMouse.click(MOUSE_LEFT); }
      else if (strcmp(cmd,"LEFT_PRESS")==0) { BootMouse.press(MOUSE_LEFT); }
      else if (strcmp(cmd,"LEFT_RELEASE")==0) { BootMouse.release(MOUSE_LEFT); }
      else if (strcmp(cmd,"RIGHT_CLICK")==0) { BootMouse.click(MOUSE_RIGHT); }
      else if (strcmp(cmd,"STOP")==0) { stopFlag=true; releaseAll(); }
      else if (strncmp(cmd,"WAIT_",5)==0) { delay(atoi(cmd+5)); }
      else if (strncmp(cmd,"SCR_",4)==0) { char* us=strchr(cmd+4,'_'); if (us) { screenW=atoi(cmd+4); screenH=atoi(us+1); MouseTo.setScreenResolution(screenW,screenH); } }
      else { uint8_t code=findKeyCode(cmd); if (code) tapKey(code); else if (strlen(cmd)==1) tapKey(cmd[0]); }
      cmdLen=0; memset(cmdBuffer,0,sizeof(cmdBuffer));
    } else if (cmdLen<MAX_CMD_LENGTH-1) { cmdBuffer[cmdLen++]=c; }
  }
}
