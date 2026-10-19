// app.js
const identity = require("./utils/identity");

App({
  onLaunch() {
    // 初始化匿名身份（首次访问自动生成）
    identity.getCurrentIdentity();
  },
  globalData: {},
});
