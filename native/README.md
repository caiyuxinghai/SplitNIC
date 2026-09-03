# Native modules

`DropGlass.dll` — OLE IDropTarget overlay so Explorer can drop desktop shortcuts onto the GUI.

`BindHook.dll` — injected into a 64-bit target process.

`bindhook.c` is injected into a 64-bit target process and forces Winsock
sockets onto the interface given by:

- `SPLITNIC_BIND_IP` — IPv4 address of the chosen NIC
- `SPLITNIC_IFINDEX` — Windows interface index

Build (from the repo root):

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

This uses TinyCC. The resulting `BindHook.dll` stays next to the source.
A debug log is appended to `%TEMP%\splitnic-bindhook.log`.
