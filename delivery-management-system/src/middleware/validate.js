// Minimal request-body validator: fields spec -> 400 with per-field messages.
function requireFields(spec) {
  return (req, res, next) => {
    const errors = {};
    for (const [field, rule] of Object.entries(spec)) {
      const value = req.body?.[field];
      if (rule.optional && (value === undefined || value === null || value === '')) continue;
      if (value === undefined || value === null || value === '') {
        errors[field] = 'is required';
        continue;
      }
      if (rule.type === 'string' && typeof value !== 'string') errors[field] = 'must be a string';
      if (rule.type === 'number' && typeof value !== 'number') errors[field] = 'must be a number';
      if (rule.enum && !rule.enum.includes(value)) errors[field] = `must be one of: ${rule.enum.join(', ')}`;
      if (rule.minLength && typeof value === 'string' && value.trim().length < rule.minLength) {
        errors[field] = `must be at least ${rule.minLength} characters`;
      }
      if (rule.pattern && typeof value === 'string' && !rule.pattern.test(value)) {
        errors[field] = rule.patternMessage || 'has an invalid format';
      }
    }
    if (Object.keys(errors).length) return res.status(400).json({ error: 'Validation failed', fields: errors });
    next();
  };
}

module.exports = { requireFields };
