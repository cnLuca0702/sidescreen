# Third-party components and references / 第三方组件与参考

- **psutil** is the runtime dependency. Its upstream license is BSD-3-Clause; installation supplies its own license notices. Upstream: https://github.com/giampaolo/psutil and https://pypi.org/project/psutil/ . SideScreen does not vendor psutil source.
- **OpenStats** is a conceptual reference for some monitoring and optional proxy-probe behavior: https://github.com/gentpan/OpenStats . SideScreen samples metrics independently; it does not use a private OpenStats API, service, account or database. The reference is not an affiliation or endorsement.

项目没有打包第三方源码；psutil通过requirements安装并保留其上游许可。OpenStats仅作为相关思路参考，不代表官方关系或背书。SideScreen自身许可证尚未选定，不能把依赖许可证当成本项目的授权。
