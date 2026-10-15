/* SPDX-License-Identifier: MIT
 * A Windows process called steam.exe for Wauncher's process-name check.
 * This is NOT a Steam client or an authentication implementation. Proton's
 * Steam bridge and the native Steam client supply the real authentication.
 * No CRT or Windows SDK headers needed; these are the Win64 ABI declarations.
 */
typedef unsigned long DWORD;
typedef int BOOL;
typedef void *HANDLE;
typedef __WCHAR_TYPE__ WCHAR;
typedef struct {
    DWORD cb;
    WCHAR *reserved, *desktop, *title;
    DWORD x, y, xsize, ysize, xchars, ychars, fill, flags;
    unsigned short show, reserved_size;
    unsigned char *reserved_data;
    HANDLE in, out, err;
} STARTUPINFOW;
typedef struct {
    HANDLE process, thread;
    DWORD process_id, thread_id;
} PROCESS_INFORMATION;

#define API __declspec(dllimport)
API BOOL __stdcall CreateProcessW(const WCHAR *, WCHAR *, void *, void *, BOOL,
                                 DWORD, void *, const WCHAR *, STARTUPINFOW *, PROCESS_INFORMATION *);
API DWORD __stdcall WaitForSingleObject(HANDLE, DWORD);
API BOOL __stdcall GetExitCodeProcess(HANDLE, DWORD *);
API BOOL __stdcall CloseHandle(HANDLE);
API void __stdcall ExitProcess(DWORD);
API HANDLE __stdcall GetStdHandle(DWORD);
API BOOL __stdcall WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);

_Static_assert(sizeof(STARTUPINFOW) == 104, "Requires Win64 ABI");

void mainCRTStartup(void)
{
    static STARTUPINFOW startup;
    static PROCESS_INFORMATION child;
    DWORD status = 1;
    static WCHAR command[] = L"\"wauncher.exe\"";
    startup.cb = sizeof(startup);
    if (!CreateProcessW(L"wauncher.exe", command, 0, 0, 0, 0, 0, 0, &startup, &child)) {
        static const char error[] = "Wauncher Linux: cannot start wauncher.exe in the game directory.\r\n";
        DWORD written;
        WriteFile(GetStdHandle((DWORD)-12), error, sizeof(error) - 1, &written, 0);
        ExitProcess(1);
    }
    CloseHandle(child.thread);
    if (WaitForSingleObject(child.process, 0xffffffffUL) == 0)
        GetExitCodeProcess(child.process, &status);
    CloseHandle(child.process);
    ExitProcess(status);
}
