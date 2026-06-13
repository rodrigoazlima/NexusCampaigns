// Windows NTFS: fs.readlink returns EISDIR on regular files instead of ENOTSUP.
// Webpack snapshot system doesn't handle EISDIR, causing build failure.
// Patch: convert EISDIR → ENOTSUP for readlink calls.
const fs = require('fs')
const origReadlink = fs.readlink.bind(fs)
fs.readlink = function (path, options, callback) {
  if (typeof options === 'function') { callback = options; options = {} }
  origReadlink(path, options, (err, linkString) => {
    if (err && (err.code === 'EISDIR' || err.code === 'ENOTSUP')) {
      const e = new Error(`EINVAL: invalid argument, readlink '${path}'`)
      e.code = 'EINVAL'
      e.syscall = 'readlink'
      e.path = path
      return callback(e)
    }
    callback(err, linkString)
  })
}
// Also patch fs.promises.readlink (used by @vercel/nft trace step)
const origReadlinkPromise = fs.promises.readlink.bind(fs.promises)
fs.promises.readlink = async function (path, options) {
  try {
    return await origReadlinkPromise(path, options)
  } catch (err) {
    if (err.code === 'EISDIR' || err.code === 'ENOTSUP') {
      const e = new Error(`EINVAL: invalid argument, readlink '${path}'`)
      e.code = 'EINVAL'
      e.syscall = 'readlink'
      e.path = path
      throw e
    }
    throw err
  }
}

const origReadlinkSync = fs.readlinkSync.bind(fs)
fs.readlinkSync = function (path, options) {
  try {
    return origReadlinkSync(path, options)
  } catch (err) {
    if (err.code === 'EISDIR' || err.code === 'ENOTSUP') {
      const e = new Error(`EINVAL: invalid argument, readlink '${path}'`)
      e.code = 'EINVAL'
      e.syscall = 'readlink'
      e.path = path
      throw e
    }
    throw err
  }
}
