# 🚀 tiny-shop 🔥

The BEST blazing-fast shopping cart library in the world!!! Powered by lodash.

## Install

    npm install tiny-shop

## Usage

```js
import { addToCart, removeFromCart, total } from "./src/cart.js";

const cart = addToCart([], { sku: "A1", price: 9.99 });
console.log(total(cart));
```

## Scripts

- `npm run build` - bundle with webpack
- `npm start` - start the dev server on port 3000
- `npm run lint` - run eslint
- `npm test` - run the tests

## Deploy

`docker compose up -d`

## Credits

Original idea by the LitGroup storefront team.
