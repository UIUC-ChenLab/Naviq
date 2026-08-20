#ifndef DATA_VIEW_H
#define DATA_VIEW_H

#include <cstdint>
#include <vector>
#include <memory>
#include <stdexcept>
#include <iterator>

class DataView {
public:
	DataView(std::shared_ptr<std::vector<uint8_t>> contents, size_t total_bytes, size_t start_idx);
	DataView();
	std::shared_ptr<std::vector<uint8_t>> contents;

	// Element access
	uint8_t operator[](size_t i) const;
	uint8_t& operator[](size_t i);

	// Size and data access
	size_t size() const { return total_bytes_; }
	uint8_t* data() { return contents->data() + start_idx_; }
	const uint8_t* data() const { return contents->data() + start_idx_; }

	// Iterators
	uint8_t* begin() { return contents->data() + start_idx_; }
	const uint8_t* begin() const { return contents->data() + start_idx_; }
	const uint8_t* cbegin() const { return contents->data() + start_idx_; }
	uint8_t* end() { return contents->data() + start_idx_ + total_bytes_; }
	const uint8_t* end() const { return contents->data() + start_idx_ + total_bytes_; }
	const uint8_t* cend() const { return contents->data() + start_idx_ + total_bytes_; }

	// Copy assignment from another DataView (creates a new view)
	DataView& operator=(const DataView& other);

	// Create a subview that is a strict subset of this view
	// offset: byte offset from the start of this view
	// length: number of bytes in the subview
	DataView subview(size_t offset, size_t length) const;

private:
	size_t total_bytes_;
	size_t start_idx_;
};

#endif
