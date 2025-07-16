@echo off
set PYTHONPATH=%~dp0
IF "%1"=="install" (
    python service.py install
    echo Service installed successfully
) ELSE IF "%1"=="start" (
    net start FP2PivotAppService
    echo Service started
) ELSE IF "%1"=="stop" (
    net stop FP2PivotAppService
    echo Service stopped
) ELSE IF "%1"=="remove" (
    python service.py remove
    echo Service removed
) ELSE (
    echo Usage: manage_service.bat [install^|start^|stop^|remove]
)