#include "DataView.h"

DataView::DataView(std::shared_ptr<std::vector<uint8_t>> contents, size_t total_bytes, size_t start_idx) : 
	contents(contents), total_bytes_(total_bytes), start_idx_(start_idx) 
{
	// Allow null contents only if total_bytes is 0 (empty view)
	if (contents == nullptr && total_bytes_ > 0) {
		throw std::runtime_error("DataView: contents is null but total_bytes > 0");
	}
	if (contents != nullptr && start_idx_ + total_bytes_ > contents->size()) {
		throw std::runtime_error("DataView: start_idx + total_bytes is greater than the size of the contents");
	}
}

DataView::DataView() : contents(nullptr), total_bytes_(0), start_idx_(0) {
}

uint8_t DataView::operator[](size_t i) const {
	if (contents == nullptr) {
		throw std::runtime_error("DataView: attempting to access empty view");
	}
	if (i >= total_bytes_) {
		throw std::runtime_error("DataView: index is greater than the total number of bytes");
	}
    return (*contents)[start_idx_ + i];
}

uint8_t& DataView::operator[](size_t i) {
	if (contents == nullptr) {
		throw std::runtime_error("DataView: attempting to access empty view");
	}
	if (i >= total_bytes_) {
		throw std::runtime_error("DataView: index is greater than the total number of bytes");
	}
    return (*contents)[start_idx_ + i];
}

DataView& DataView::operator=(const DataView& other) {
	if (this != &other) {
		contents = other.contents;
		total_bytes_ = other.total_bytes_;
		start_idx_ = other.start_idx_;
	}
	return *this;
}

DataView DataView::subview(size_t offset, size_t length) const {
	// Validate that the subview is within bounds of the current view
	if (offset + length > total_bytes_) {
		throw std::runtime_error("DataView::subview: offset + length exceeds the size of the current view");
	}
	
	// If contents is null (empty view), return an empty DataView
	if (contents == nullptr) {
		return DataView();
	}
	
	// Create a new view with adjusted start index
	// The new view points to the same underlying buffer but starts at (start_idx_ + offset)
	return DataView(contents, length, start_idx_ + offset);
}
