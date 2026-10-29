@echo off
chcp 65001 >nul
set BASE=C:\mysql-8.0.45-winx64
"%BASE%\bin\mysqladmin.exe" -u root -h 127.0.0.1 -P 3307 --skip-password shutdown
echo 开发实例已停止
