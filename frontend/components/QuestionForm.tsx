'use client';

interface Props {
  question: string;
  onQuestionChange: (value: string) => void;
  onSubmit: (question: string) => void;
  loading: boolean;
}

export default function QuestionForm({ question, onQuestionChange, onSubmit, loading }: Props) {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(question);
  };

  return (
    <form onSubmit={handleSubmit} className="mb-6">
      <label htmlFor="question-input" className="block text-sm font-semibold text-gray-300 mb-2">
        Natural-Language Question
      </label>
      <textarea
        id="question-input"
        className="w-full h-28 p-3 rounded-md bg-gray-800 border border-gray-600 text-gray-100 text-sm
                   focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        placeholder="e.g. Which doctor has the highest number of appointments?"
        value={question}
        onChange={(e) => onQuestionChange(e.target.value)}
        disabled={loading}
      />
      <button
        id="generate-report-btn"
        type="submit"
        disabled={loading || question.trim() === ''}
        className="mt-3 px-5 py-2 rounded-md bg-blue-600 text-white text-sm font-semibold
                   hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? 'Generating report…' : 'Generate Report'}
      </button>
    </form>
  );
}
