#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <linux/uinput.h>

static void emit(int fd, int type, int code, int val) {
    struct input_event ie;
    memset(&ie, 0, sizeof(ie));
    ie.type = type;
    ie.code = code;
    ie.value = val;
    write(fd, &ie, sizeof(ie));
}

static void syn(int fd) {
    emit(fd, EV_SYN, SYN_REPORT, 0);
}

static void tap(int fd, int code, int duration_ms) {
    emit(fd, EV_KEY, code, 1);
    syn(fd);
    usleep(duration_ms * 1000);
    emit(fd, EV_KEY, code, 0);
    syn(fd);
    usleep(duration_ms * 1000);
}

static void tap_shifted(int fd, int code, int duration_ms) {
    emit(fd, EV_KEY, KEY_LEFTSHIFT, 1);
    syn(fd);
    usleep(20000);
    emit(fd, EV_KEY, code, 1);
    syn(fd);
    usleep(duration_ms * 1000);
    emit(fd, EV_KEY, code, 0);
    syn(fd);
    usleep(duration_ms * 1000);
    emit(fd, EV_KEY, KEY_LEFTSHIFT, 0);
    syn(fd);
    usleep(20000);
}

static void type_char(int fd, char c) {
    if (c >= 'a' && c <= 'z') {
        int map[] = {
            KEY_A, KEY_B, KEY_C, KEY_D, KEY_E, KEY_F, KEY_G, KEY_H, KEY_I,
            KEY_J, KEY_K, KEY_L, KEY_M, KEY_N, KEY_O, KEY_P, KEY_Q, KEY_R,
            KEY_S, KEY_T, KEY_U, KEY_V, KEY_W, KEY_X, KEY_Y, KEY_Z
        };
        tap(fd, map[c - 'a'], 15);
    } else if (c >= 'A' && c <= 'Z') {
        int map[] = {
            KEY_A, KEY_B, KEY_C, KEY_D, KEY_E, KEY_F, KEY_G, KEY_H, KEY_I,
            KEY_J, KEY_K, KEY_L, KEY_M, KEY_N, KEY_O, KEY_P, KEY_Q, KEY_R,
            KEY_S, KEY_T, KEY_U, KEY_V, KEY_W, KEY_X, KEY_Y, KEY_Z
        };
        tap_shifted(fd, map[c - 'A'], 15);
    } else if (c >= '0' && c <= '9') {
        int map[] = {
            KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9
        };
        tap(fd, map[c - '0'], 15);
    } else {
        switch (c) {
            case ' ': tap(fd, KEY_SPACE, 15); break;
            case '!': tap_shifted(fd, KEY_1, 15); break;
            case '@': tap_shifted(fd, KEY_2, 15); break;
            case '#': tap_shifted(fd, KEY_3, 15); break;
            case '$': tap_shifted(fd, KEY_4, 15); break;
            case '%': tap_shifted(fd, KEY_5, 15); break;
            case '^': tap_shifted(fd, KEY_6, 15); break;
            case '&': tap_shifted(fd, KEY_7, 15); break;
            case '*': tap_shifted(fd, KEY_8, 15); break;
            case '(': tap_shifted(fd, KEY_9, 15); break;
            case ')': tap_shifted(fd, KEY_0, 15); break;
            case '-': tap(fd, KEY_MINUS, 15); break;
            case '_': tap_shifted(fd, KEY_MINUS, 15); break;
            case '=': tap(fd, KEY_EQUAL, 15); break;
            case '+': tap_shifted(fd, KEY_EQUAL, 15); break;
            case '[': tap(fd, KEY_LEFTBRACE, 15); break;
            case '{': tap_shifted(fd, KEY_LEFTBRACE, 15); break;
            case ']': tap(fd, KEY_RIGHTBRACE, 15); break;
            case '}': tap_shifted(fd, KEY_RIGHTBRACE, 15); break;
            case '\\': tap(fd, KEY_BACKSLASH, 15); break;
            case '|': tap_shifted(fd, KEY_BACKSLASH, 15); break;
            case ';': tap(fd, KEY_SEMICOLON, 15); break;
            case ':': tap_shifted(fd, KEY_SEMICOLON, 15); break;
            case '\'': tap(fd, KEY_APOSTROPHE, 15); break;
            case '"': tap_shifted(fd, KEY_APOSTROPHE, 15); break;
            case ',': tap(fd, KEY_COMMA, 15); break;
            case '<': tap_shifted(fd, KEY_COMMA, 15); break;
            case '.': tap(fd, KEY_DOT, 15); break;
            case '>': tap_shifted(fd, KEY_DOT, 15); break;
            case '/': tap(fd, KEY_SLASH, 15); break;
            case '?': tap_shifted(fd, KEY_SLASH, 15); break;
            default: break;
        }
    }
}

int main(int argc, char **argv) {
    if (argc < 2) return 0;
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) {
        perror("open /dev/uinput");
        return 1;
    }
    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    ioctl(fd, UI_SET_EVBIT, EV_SYN);
    for (int i = 0; i < 256; i++) {
        ioctl(fd, UI_SET_KEYBIT, i);
    }
    struct uinput_setup usetup;
    memset(&usetup, 0, sizeof(usetup));
    usetup.id.bustype = BUS_USB;
    usetup.id.vendor = 0x1234;
    usetup.id.product = 0x5678;
    strcpy(usetup.name, "Hermes Uinput Virtual Keyboard");
    ioctl(fd, UI_DEV_SETUP, &usetup);
    ioctl(fd, UI_DEV_CREATE);
    usleep(50000); // 50ms for device recognition

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "slash") == 0) {
            tap(fd, KEY_SLASH, 30);
        } else if (strcmp(arg, "enter") == 0 || strcmp(arg, "return") == 0) {
            tap(fd, KEY_ENTER, 30);
        } else if (strcmp(arg, "esc") == 0 || strcmp(arg, "escape") == 0) {
            tap(fd, KEY_ESC, 30);
        } else if (strcmp(arg, "backspace") == 0 || strcmp(arg, "bksp") == 0) {
            tap(fd, KEY_BACKSPACE, 30);
        } else if (strcmp(arg, "t") == 0) {
            tap(fd, KEY_T, 30);
        } else if (strncmp(arg, "sleep:", 6) == 0) {
            int ms = atoi(arg + 6);
            if (ms > 0) usleep(ms * 1000);
        } else if (strncmp(arg, "type:", 5) == 0) {
            const char *p = arg + 5;
            while (*p) {
                type_char(fd, *p++);
            }
        }
    }

    usleep(20000);
    ioctl(fd, UI_DEV_DESTROY);
    close(fd);
    return 0;
}
