interface Option<T extends string> {
  value: T;
  label: string;
  description?: string;
}

interface SegmentedControlProps<T extends string> {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
}

export default function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: SegmentedControlProps<T>) {
  return (
    <fieldset className="appearance-control-group">
      <legend>{label}</legend>
      <div className="appearance-segmented-control">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-label={option.label}
            aria-checked={value === option.value}
            className="appearance-segment"
            onClick={() => onChange(option.value)}
          >
            <span>{option.label}</span>
            {option.description && <small aria-hidden="true">{option.description}</small>}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
