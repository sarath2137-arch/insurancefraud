require('@nomicfoundation/hardhat-toolbox');
const { subtask } = require('hardhat/config');
const { TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD } = require('hardhat/builtin-tasks/task-names');

// Use the pinned local compiler package so `npm run compile` works offline.
subtask(TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD).setAction(async ({ solcVersion }, _hre, runSuper) => {
  if (solcVersion !== '0.8.24') return runSuper();
  const solc = require('solc');
  return {
    compilerPath: require.resolve('solc/soljson.js'),
    isSolcJs: true,
    version: solcVersion,
    longVersion: solc.version(),
  };
});

module.exports = {
  solidity: '0.8.24',
  networks: {
    // Deliberately local only. Deployment scripts do not target a public network.
    localhost: { url: 'http://127.0.0.1:8545' },
  },
};
