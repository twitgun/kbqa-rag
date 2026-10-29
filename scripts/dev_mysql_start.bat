@echo off
chcp 65001 >nul
set BASE=C:\mysql-8.0.45-winx64
set DATA=D:\bishe\data\mysql_dev

if not exist "%DATA%" (
  echo 初始化开发实例数据目录...
  "%BASE%\bin\mysqld.exe" --initialize-insecure --basedir="%BASE%" --datadir="%DATA%"
)

echo 启动开发实例：127.0.0.1:3307（与系统 MySQL80 的 3306 互不影响）
start "" "%BASE%\bin\mysqld.exe" --basedir="%BASE%" --datadir="%DATA%" --port=3307 --mysqlx=0 --server-id=88
timeout /t 5 >nul
"%BASE%\bin\mysql.exe" -u root -h 127.0.0.1 -P 3307 --skip-password -e "SELECT VERSION();"
