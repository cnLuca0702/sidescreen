# Third-party components and references / 第三方组件与参考

- **psutil** is the runtime dependency. Its upstream license is BSD-3-Clause; installation supplies its own license notices. Upstream: https://github.com/giampaolo/psutil and https://pypi.org/project/psutil/ . SideScreen does not vendor psutil source.
- **OpenStats** is a conceptual reference for some monitoring and optional proxy-probe behavior: https://github.com/gentpan/OpenStats . SideScreen samples metrics independently; it does not use a private OpenStats API, service, account or database. The reference is not an affiliation or endorsement.

项目没有打包第三方源码；psutil通过requirements安装并保留其上游许可。OpenStats仅作为相关思路参考，不代表官方关系或背书。SideScreen项目自有代码采用[MIT许可证](LICENSE)；该授权不替代或覆盖第三方组件各自的许可。
