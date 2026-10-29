# 全局依赖项

有时，我们要为整个应用添加依赖项。

通过与将 `dependencies` 添加到*路径操作装饰器* 类似的方式，可以把依赖项添加至整个 `FastAPI` 应用。

这样一来，就可以为所有*路径操作*应用该依赖项：

```python
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException

async def verify_token(x_token: Annotated[str, Header()]):
    if x_token != "fake-super-secret-token":
        raise HTTPException(status_code=400, detail="X-Token header invalid")

async def verify_key(x_key: Annotated[str, Header()]):
    if x_key != "fake-super-secret-key":
        raise HTTPException(status_code=400, detail="X-Key header invalid")
    return x_key

app = FastAPI(dependencies=[Depends(verify_token), Depends(verify_key)])

@app.get("/items/")
async def read_items():
    return [{"item": "Portal Gun"}, {"item": "Plumbus"}]

@app.get("/users/")
async def read_users():
    return [{"username": "Rick"}, {"username": "Morty"}]
```

🤓 Other versions and variants

Tip

Prefer to use the `Annotated` version if possible.

```python
from fastapi import Depends, FastAPI, Header, HTTPException

async def verify_token(x_token: str = Header()):
    if x_token != "fake-super-secret-token":
        raise HTTPException(status_code=400, detail="X-Token header invalid")

async def verify_key(x_key: str = Header()):
    if x_key != "fake-super-secret-key":
        raise HTTPException(status_code=400, detail="X-Key header invalid")
    return x_key

app = FastAPI(dependencies=[Depends(verify_token), Depends(verify_key)])

@app.get("/items/")
async def read_items():
    return [{"item": "Portal Gun"}, {"item": "Plumbus"}]

@app.get("/users/")
async def read_users():
    return [{"username": "Rick"}, {"username": "Morty"}]
```

将 `dependencies` 添加到*路径操作装饰器* 一章的思路均适用于全局依赖项， 在本例中，这些依赖项可以用于应用中的所有*路径操作*。

## 为一组路径操作定义依赖项

稍后，大型应用 - 多文件一章中会介绍如何使用多个文件创建大型应用程序，在这一章中，你将了解到如何为一组*路径操作*声明单个 `dependencies` 参数。