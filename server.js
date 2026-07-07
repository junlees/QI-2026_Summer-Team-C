const express = require('express');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.static(__dirname, { extensions: ['html'] }));

app.get('/healthz', (req, res) => {
  res.status(200).send('ok');
});

app.use((req, res) => {
  res.status(404).send('404 Not Found');
});

app.listen(PORT, () => {
  console.log(`Pace Runner server listening on port ${PORT}`);
});
