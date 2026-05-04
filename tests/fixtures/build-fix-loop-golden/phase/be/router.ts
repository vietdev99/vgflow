import { Router } from 'express';
const r = Router();
r.post('/api/v1/admin/invoices/:id/payments', handler);
export default r;
