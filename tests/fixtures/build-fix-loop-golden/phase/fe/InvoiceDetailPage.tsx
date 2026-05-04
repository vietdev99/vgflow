import axios from 'axios';
export function InvoiceDetailPage({ id }: { id: string }) {
  // BUG: GET endpoint does not exist on BE
  axios.get('/api/v1/admin/invoices/' + id + '/payments');
  return null;
}
