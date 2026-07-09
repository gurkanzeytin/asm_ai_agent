import axios from 'axios';
import { ReportResponse } from '@/types/report';

const apiClient = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Sends a natural-language question to the backend reporting pipeline
 * and returns the fully structured ReportResponse.
 */
export async function generateReport(question: string): Promise<ReportResponse> {
  const response = await apiClient.post<ReportResponse>('/report/', { question });
  return response.data;
}


